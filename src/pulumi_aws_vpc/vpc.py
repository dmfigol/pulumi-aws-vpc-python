import pulumi_aws as aws
import pulumi
from pulumi import ResourceOptions, ComponentResource, Output
from typing import Any, Union, NamedTuple, Optional, Tuple

from pulumi_aws_vpc.config import VPCConfig, AttachmentType
from pulumi_aws_vpc.constants import RESOURCE_TYPE


class RouteTableInfo(NamedTuple):
    rt: aws.ec2.RouteTable
    routes: dict[str, aws.ec2.Route]


class SubnetInfo(NamedTuple):
    subnet: aws.ec2.Subnet
    route_table: Optional[aws.ec2.RouteTable] = None


class InternetGatewayInfo(NamedTuple):
    igw: aws.ec2.InternetGateway
    rt: Optional[str] = None


class VirtualGatewayInfo(NamedTuple):
    vgw: aws.ec2.VpnGateway
    rt: Optional[str] = None


class AttachmentInfo(NamedTuple):
    type: AttachmentType
    attachment: Union[
        aws.ec2transitgateway.VpcAttachment, aws.networkmanager.VpcAttachment
    ]
    tgw_id: Optional[str] = None
    core_network_id: Optional[str] = None
    association: Optional[aws.ec2.RouteTableAssociation] = None
    propagations: list[aws.ec2.RouteTableAssociation] = []


class VPC(ComponentResource):
    def __init__(
        self,
        name: str,
        config: Union[VPCConfig, dict[str, Any]],
        opts: ResourceOptions = None,
    ):
        if isinstance(config, dict):
            config = VPCConfig(**config)
        self.config = config
        super().__init__(RESOURCE_TYPE, name, None, opts)

        self.common_tags = config.common_tags

        self.vpc = self._create_vpc(config)
        self.secondary_cidrs = VPC._create_secondary_cidrs(config, vpc=self.vpc)
        self.elastic_ips = self._create_elastic_ips(config)

        self.subnets = VPC._create_subnets(
            config,
            vpc=self.vpc,
            secondary_cidrs=self.secondary_cidrs,
        )

        self.nat_gateways = VPC._create_nat_gateways(
            config, subnets=self.subnets, elastic_ips=self.elastic_ips
        )

        self.internet_gateway = VPC._create_internet_gateway(config, vpc=self.vpc)

        self.virtual_gateway = VPC._create_virtual_gateway(config, vpc=self.vpc)

        self.attachments = VPC._create_attachments(
            config, subnets=self.subnets, vpc=self.vpc
        )

        self.route_tables = VPC._create_route_tables(
            config,
            vpc=self.vpc,
            igw_id=self.igw_id,
            vgw_id=self.vgw_id,
            attachments=self.attachments,
            nat_gateways=self.nat_gateways,
        )

        self.rt_associations = VPC._create_route_table_associations(
            self.route_tables,
            self.subnets,
            igw_info=self.internet_gateway,
            vgw_info=self.virtual_gateway,
            vpc=self.vpc,
        )

        self.register_outputs(self.outputs)

    @staticmethod
    def get_az_ids() -> list[str]:
        return aws.get_availability_zones(state="available").zone_ids

    @staticmethod
    def get_az_id_prefix() -> str:
        """euc1-az1 -> euc1-az"""
        return VPC.get_az_ids()[0][:-1]

    def _create_vpc(self, config: VPCConfig) -> aws.ec2.Vpc:
        result = aws.ec2.Vpc(
            "vpc",
            cidr_block=config.primary_cidr.cidr,
            instance_tenancy="default",
            enable_dns_hostnames=True,
            enable_dns_support=True,
            tags=VPC.build_tags(config.common_tags, config.tags, Name=config.name),
            opts=ResourceOptions(parent=self),
        )
        return result

    @staticmethod
    def _create_secondary_cidrs(
        config: VPCConfig, vpc: aws.ec2.Vpc
    ) -> dict[str, aws.ec2.VpcIpv4CidrBlockAssociation]:
        result = {}
        for cidr in config.secondary_cidrs:
            secondary_cidr = aws.ec2.VpcIpv4CidrBlockAssociation(
                cidr.cidr,
                vpc_id=vpc.id,
                cidr_block=cidr.cidr,
                opts=ResourceOptions(parent=vpc),
            )
            result[cidr.cidr] = secondary_cidr
        return result

    def _create_elastic_ips(self, config: VPCConfig) -> dict[str, aws.ec2.Eip]:
        result = {}
        for eip_config in config.elastic_ips:
            eip = aws.ec2.Eip(
                eip_config.name,
                **eip_config.dump(),
                tags=VPC.build_tags(
                    config.common_tags, eip_config.tags, Name=eip_config.name
                ),
                opts=ResourceOptions(parent=self),
            )
            result[eip_config.name] = eip
        return result

    @staticmethod
    def _create_subnets(
        config: VPCConfig,
        vpc: aws.ec2.Vpc,
        secondary_cidrs: dict[str, aws.ec2.VpcIpv4CidrBlockAssociation],
    ) -> dict[str, aws.ec2.Subnet]:
        result = {}
        az_id_prefix = VPC.get_az_id_prefix()
        for vpc_cidr in config.cidrs:
            for subnet_config in vpc_cidr.get_subnets():
                if vpc_cidr == config.primary_cidr:
                    dependencies = []
                else:
                    dependencies = [secondary_cidrs[vpc_cidr.cidr]]

                if subnet_config.az_id.isdigit():
                    az_id = f"{az_id_prefix}{subnet_config.az_id}"
                else:
                    az_id = subnet_config.az_id

                subnet = aws.ec2.Subnet(
                    subnet_config.name,
                    vpc_id=vpc.id,
                    availability_zone_id=az_id,
                    cidr_block=subnet_config.cidr,
                    tags=VPC.build_tags(
                        config.common_tags,
                        subnet_config.tags,
                        Name=f"{config.name}-{subnet_config.name}",
                    ),
                    opts=ResourceOptions(
                        depends_on=dependencies, parent=vpc, delete_before_replace=True
                    ),
                )
                result[subnet_config.name] = SubnetInfo(
                    subnet=subnet, route_table=subnet_config.route_table
                )
        return result

    @staticmethod
    def _create_nat_gateways(
        config: VPCConfig,
        subnets: dict[str, SubnetInfo],
        elastic_ips: dict[str, aws.ec2.Eip],
    ) -> dict[str, aws.ec2.NatGateway]:
        result = {}
        for nat_config in config.nat_gateways:
            primary_eip_id = None
            if nat_config.is_public:
                primary_eip_id = elastic_ips[nat_config.eips[0]].id
            tags = VPC.build_tags(
                config.common_tags,
                nat_config.tags,
                Name=f"{config.name}_{nat_config.name}",
            )
            subnet = subnets[nat_config.subnet].subnet
            nat_gw = aws.ec2.NatGateway(
                nat_config.name,
                subnet_id=subnet.id,
                connectivity_type=nat_config.type.value,
                allocation_id=primary_eip_id,
                secondary_allocation_ids=[
                    elastic_ips[eip].id for eip in nat_config.eips[1:]
                ],
                tags=tags,
                opts=ResourceOptions(parent=subnet),
            )
            result[nat_config.name] = nat_gw
        return result

    @staticmethod
    def _create_route_tables(
        config: VPCConfig,
        vpc: aws.ec2.Vpc,
        igw_id: Optional[Output[str]],
        vgw_id: Optional[Output[str]],
        attachments: dict[str, AttachmentInfo],
        nat_gateways: dict[str, aws.ec2.NatGateway],
    ) -> dict[str, RouteTableInfo]:
        result = {}
        for rt_config in config.route_tables:
            route_table = aws.ec2.RouteTable(
                rt_config.name,
                vpc_id=vpc.id,
                tags=VPC.build_tags(
                    config.common_tags,
                    rt_config.tags,
                    Name=f"{config.name}-{rt_config.name}",
                ),
                opts=ResourceOptions(parent=vpc),
            )

            routes = {}
            for route_cfg in rt_config.routes:
                if route_cfg.destination == "@rfc1918":
                    destinations = ["192.168.0.0/16", "10.0.0.0/8", "172.16.0.0/12"]
                else:
                    destinations = [route_cfg.destination]

                for destination in destinations:
                    if destination.startswith("pl-"):
                        dest_input = {"destination_prefix_list_id": destination}
                    else:
                        dest_input = {"destination_cidr_block": destination}

                    if route_cfg.next_hop == "@vgw":
                        if vgw_id is None:
                            raise ValueError("Virtual Gateway has not been created")
                        next_hop = {"gateway_id": vgw_id}

                    elif route_cfg.next_hop == "@igw":
                        if igw_id is None:
                            raise ValueError("Internet Gateway has not been created")
                        next_hop = {"gateway_id": igw_id}

                    elif route_cfg.next_hop.startswith("@attachment:"):
                        _, attachment_name = route_cfg.next_hop.split(":")
                        if attachment_name not in attachments:
                            raise ValueError(f"Attachment {attachment_name} not found")
                        att_info = attachments[attachment_name]
                        att_type = att_info.type
                        if att_type is AttachmentType.TRANSIT_GATEWAY:
                            next_hop = {"transit_gateway_id": att_info.tgw_id}
                        elif att_type is AttachmentType.CLOUDWAN:
                            next_hop = {
                                "core_network_arn": att_info.attachment.core_network_arn
                            }
                        else:
                            raise ValueError(
                                f"Attachment {attachment_name} is not a transit gateway or cloudwan"
                            )

                    elif route_cfg.next_hop.startswith("@natgw:"):
                        _, nat_gw_name = route_cfg.next_hop.split(":")
                        if nat_gw_name not in nat_gateways:
                            raise ValueError(f"NAT Gateway {nat_gw_name} not found")
                        next_hop = {"nat_gateway_id": nat_gateways[nat_gw_name].id}

                    else:
                        next_hop = {"gateway_id": route_cfg.next_hop}

                    route = aws.ec2.Route(
                        f"{rt_config.name}_{destination}",
                        route_table_id=route_table.id,
                        **dest_input,
                        **next_hop,
                        opts=ResourceOptions(parent=route_table),
                    )
                    routes[destination] = route
            result[rt_config.name] = RouteTableInfo(rt=route_table, routes=routes)
        return result

    @staticmethod
    def _create_route_table_associations(
        route_tables: dict[str, RouteTableInfo],
        subnets: dict[str, SubnetInfo],
        igw_info: InternetGatewayInfo,
        vgw_info: VirtualGatewayInfo,
        vpc: aws.ec2.Vpc,
    ) -> Tuple[
        dict[str, aws.ec2.RouteTableAssociation],
        Optional[aws.ec2.RouteTableAssociation],
        Optional[aws.ec2.RouteTableAssociation],
    ]:
        subnet_rt_associations = {}
        igw_rt_association = None
        vgw_rt_association = None
        for subnet_name, subnet_info in subnets.items():
            rt_name = subnet_info.route_table
            if rt_name is None:
                continue
            rt_id = route_tables[rt_name].rt.id
            association = aws.ec2.RouteTableAssociation(
                f"{subnet_name}_{rt_name}",
                route_table_id=rt_id,
                subnet_id=subnet_info.subnet.id,
                opts=ResourceOptions(parent=subnet_info.subnet),
            )
            subnet_rt_associations[subnet_name] = association

        if igw_info.rt:
            igw_rt_association = aws.ec2.RouteTableAssociation(
                f"igw_{igw_info.rt}",
                route_table_id=route_tables[igw_info.rt].rt.id,
                gateway_id=igw_info.igw.id,
                opts=ResourceOptions(parent=igw_info.igw),
            )

        if vgw_info.rt:
            vgw_rt_association = aws.ec2.RouteTableAssociation(
                f"vgw_{vgw_info.rt}",
                route_table_id=route_tables[vgw_info.rt].rt.id,
                gateway_id=vgw_info.vgw.id,
                opts=ResourceOptions(parent=vgw_info.vgw),
            )

        return subnet_rt_associations, igw_rt_association, vgw_rt_association

    @staticmethod
    def _create_internet_gateway(
        config: VPCConfig, vpc: aws.ec2.Vpc
    ) -> InternetGatewayInfo:
        if config.internet_gateway is None:
            return InternetGatewayInfo(igw=None, rt=None)
        igw = aws.ec2.InternetGateway(
            "igw",
            vpc_id=vpc.id,
            tags=VPC.build_tags(
                config.common_tags,
                config.internet_gateway.tags,
                Name=f"{config.name}-igw",
            ),
            opts=ResourceOptions(parent=vpc),
        )
        return InternetGatewayInfo(igw=igw, rt=config.internet_gateway.route_table)

    @staticmethod
    def _create_virtual_gateway(
        config: VPCConfig, vpc: aws.ec2.Vpc
    ) -> VirtualGatewayInfo:
        if config.virtual_gateway is None:
            return VirtualGatewayInfo(None, None)
        vgw = aws.ec2.VpnGateway(
            "vgw",
            vpc_id=vpc.id,
            amazon_side_asn=config.virtual_gateway.asn,
            tags=VPC.build_tags(
                config.common_tags,
                config.virtual_gateway.tags,
                Name=f"{config.name}-vgw",
            ),
            opts=ResourceOptions(parent=vpc),
        )
        return VirtualGatewayInfo(vgw=vgw, rt=config.virtual_gateway.route_table)

    @staticmethod
    def _create_attachments(
        config: VPCConfig, subnets: dict[str, SubnetInfo], vpc: aws.ec2.Vpc
    ) -> dict[
        str,
        AttachmentInfo,
    ]:
        attachments = {}
        for att_config in config.attachments:
            tags = VPC.build_tags(
                config.common_tags,
                att_config.tags,
                Name=f"{config.name}-vpc-attachment",
            )
            if att_config.type is AttachmentType.TRANSIT_GATEWAY:
                attachment = aws.ec2transitgateway.VpcAttachment(
                    att_config.name,
                    transit_gateway_id=att_config.tgw_id,
                    vpc_id=vpc.id,
                    subnet_ids=[
                        subnets[subnet_name].subnet.id
                        for subnet_name in att_config.subnets
                    ],
                    tags=tags,
                    opts=ResourceOptions(parent=vpc),
                )
                # TODO: association and propagation cross account
                # use opts=ResourceOptions(provider=provider)
                association = None
                if att_config.association_rt:
                    association = aws.ec2transitgateway.RouteTableAssociation(
                        f"{att_config.association_rt}_association",
                        transit_gateway_attachment_id=attachment.id,
                        transit_gateway_route_table_id=att_config.association_rt,
                        opts=ResourceOptions(parent=attachment),
                    )
                propagations = [
                    aws.ec2transitgateway.RouteTablePropagation(
                        f"{propagation_rt}_propagation",
                        transit_gateway_attachment_id=attachment.id,
                        transit_gateway_route_table_id=propagation_rt,
                        opts=ResourceOptions(parent=attachment),
                    )
                    for propagation_rt in att_config.propagation_rts
                ]
                attachments[att_config.name] = AttachmentInfo(
                    type=AttachmentType.TRANSIT_GATEWAY,
                    attachment=attachment,
                    association=association,
                    propagations=propagations,
                    tgw_id=att_config.tgw_id,
                )

            elif att_config.type is AttachmentType.CLOUDWAN:
                attachment = aws.networkmanager.VpcAttachment(
                    att_config.name,
                    core_network_id=att_config.core_network_id,
                    subnet_arns=[
                        subnets[subnet_name].subnet.arn
                        for subnet_name in att_config.subnets
                    ],
                    vpc_arn=vpc.arn,
                    tags=tags,
                    opts=ResourceOptions(parent=vpc),
                )
                attachments[att_config.name] = AttachmentInfo(
                    type=AttachmentType.CLOUDWAN,
                    attachment=attachment,
                    core_network_id=att_config.core_network_id,
                )
        return attachments

    @property
    def outputs(self) -> dict[str, Any]:
        result = {
            "id": self.vpc.id,
            "cidrs": [
                self.vpc.cidr_block,
            ]
            + [sc.cidr_block for sc in self.secondary_cidrs.values()],
            "subnets": {
                subnet_name: {
                    "id": subnet_info.subnet.id,
                    "cidr": subnet_info.subnet.cidr_block,
                }
                for subnet_name, subnet_info in self.subnets.items()
            },
        }
        return result

    @property
    def vgw_id(self) -> Optional[Output[str]]:
        if self.virtual_gateway is None:
            return None
        return self.virtual_gateway.vgw.id

    @property
    def igw_id(self) -> Optional[Output[str]]:
        if self.internet_gateway is None:
            return None
        return self.internet_gateway.igw.id

    @property
    @pulumi.getter(name="vpcId")
    def vpc_id(self) -> Output[str]:
        return pulumi.get(self, "vpc_id")

    @staticmethod
    def build_tags(
        common_tags: dict[str, str], tags: dict[str, str], **kwargs: dict[str, str]
    ) -> dict[str, str]:
        return {**common_tags, **kwargs, **tags}
