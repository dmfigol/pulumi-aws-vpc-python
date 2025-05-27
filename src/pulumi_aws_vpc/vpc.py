import pulumi_aws as aws
import pulumi_aws_native as awscc
import pulumi
import re
from collections import defaultdict
from pulumi import ResourceOptions, Output
from typing import Any, NamedTuple, Literal, TypedDict, Protocol
from functools import cached_property
from pulumi_aws_vpc import config
from pulumi_aws_vpc.args import VPCArgs
from pulumi_aws_vpc.config import VPCConfig
from pulumi_aws_vpc.utils import divide_supernet_into_subnets
from ipaddress import ip_network, IPv4Network, IPv6Network


RESOURCE_TYPE = "aws-networking:index:VPC"
TagType = Literal["dict", "aws"]


class IPv4Cidr(Protocol):
    @property
    def cidr_block(self) -> Output[str]:
        pass


class GroupedSubnets(TypedDict):
    ipv4: defaultdict[int, list[config.Subnet]]
    ipv6: defaultdict[int, list[config.Subnet]]


class SubnetCidrs(TypedDict):
    ipv4: str | Output[str] | None
    ipv6: str | Output[str] | None


class RouteTableInfo(NamedTuple):
    rt: aws.ec2.RouteTable
    routes: dict[str, aws.ec2.Route]


class SubnetInfo(NamedTuple):
    subnet: aws.ec2.Subnet
    route_table: aws.ec2.RouteTable | None = None


class InternetGatewayInfo(NamedTuple):
    igw: aws.ec2.InternetGateway
    rt: str | None = None
    attachment: str | None = None


class VirtualPrivateGatewayInfo(NamedTuple):
    vgw: aws.ec2.VpnGateway
    rt: str | None = None
    attachment: str | None = None


class RouteTableAssociations(NamedTuple):
    subnets: dict[str, awscc.ec2.SubnetRouteTableAssociation]
    igw: awscc.ec2.GatewayRouteTableAssociation | None
    vgw: awscc.ec2.GatewayRouteTableAssociation | None


# class AttachmentInfo(NamedTuple):
#     type: AttachmentType
#     attachment: aws.ec2transitgateway.VpcAttachment | aws.networkmanager.VpcAttachment
#     tgw_id: str | None = None
#     core_network_id: str | None = None
#     association: aws.ec2.RouteTableAssociation | None = None
#     propagations: list[aws.ec2.RouteTableAssociation] = []


class VPCCidrs(TypedDict):
    ipv4: list[Output[str]]
    ipv6: list[Output[str]]


class VPC(pulumi.ComponentResource):
    vpc_id: Output[str]
    # cidrs: VPCCidrs

    def __init__(
        self,
        name: str,
        args: VPCArgs,
        opts: ResourceOptions | None = None,
    ):
        self.config = VPCConfig.model_validate(args)
        super().__init__(RESOURCE_TYPE, name, None, opts)

        self.vpc = self._create_vpc(self.config)

        self.secondary_ipv4_cidr_associations = self._create_secondary_ipv4_cidrs(
            self.config
        )
        self.ipv6_cidr_associations = self._create_ipv6_cidrs(self.config)
        self.subnets = self._create_subnets(
            self.config,
        )

        # self.elastic_ips = self._create_elastic_ips(config)

        # self.nat_gateways = VPC._create_nat_gateways(
        #     config, subnets=self.subnets, elastic_ips=self.elastic_ips
        # )

        self.internet_gateway = self._create_internet_gateway(self.config)
        self.virtual_private_gateway = self._create_virtual_private_gateway(self.config)
        self.egress_only_igw = self._create_egress_only_igw(self.config)

        # self.attachments = VPC._create_attachments(
        #     config, subnets=self.subnets, vpc=self.vpc
        # )

        self.route_tables = self._create_route_tables(self.config)
        self.endpoints = self._create_endpoints(self.config)

        self.rt_associations = self._create_route_table_associations()

        self.register_outputs(self.outputs)

    @property
    def ipv4_cidr_associations(self) -> list[IPv4Cidr]:
        return [self.vpc] + self.secondary_ipv4_cidr_associations

    @staticmethod
    def get_az_ids() -> list[str]:
        return list(aws.get_availability_zones(state="available").zone_ids)

    @staticmethod
    def get_az_id_prefix() -> list[str]:
        """euc1-az1 -> euc1-az"""
        return VPC.get_az_ids()[0][:-1]

    @cached_property
    def region(self) -> str:
        return awscc.get_region().region

    def _create_vpc(self, config: VPCConfig) -> awscc.ec2.Vpc:
        extra_args = {
            "instance_tenancy": "default",
            "enable_dns_hostnames": True,
            "enable_dns_support": True,
            **config.extra_args,
        }
        vpc = awscc.ec2.Vpc(
            "vpc",
            cidr_block=str(config.primary_cidr.cidr),
            tags=VPC.build_tags(
                config.common_tags, config.tags, format="aws", Name=config.name
            ),
            **extra_args,
            opts=ResourceOptions(parent=self),
        )
        return vpc

    def _create_secondary_ipv4_cidrs(
        self,
        config: VPCConfig,
    ) -> list[awscc.ec2.VpcCidrBlock]:
        ipv4_cidr_associations = []
        for i, cidr_obj in enumerate(config.secondary_ipv4_cidrs):
            id_ = cidr_obj.cidr or f"/{cidr_obj.size}"
            name = f"ipv4|{i + 1}|{id_}"
            ipv4_cidr = awscc.ec2.VpcCidrBlock(
                name,
                vpc_id=self.vpc.id,
                cidr_block=str(cidr_obj.cidr) if cidr_obj.cidr else None,
                ipv4_ipam_pool_id=cidr_obj.ipam_pool_id,
                ipv4_netmask_length=cidr_obj.size,
                opts=ResourceOptions(parent=self.vpc),
            )
            ipv4_cidr_associations.append(ipv4_cidr)
        return ipv4_cidr_associations

    def _create_ipv6_cidrs(
        self,
        config: VPCConfig,
    ) -> list[awscc.ec2.VpcCidrBlock]:
        ipv6_cidr_associations = []
        for i, cidr_obj in enumerate(config.cidrs.ipv6):
            id_ = cidr_obj.cidr or f"/{cidr_obj.size}"
            name = f"ipv6|{i}|{id_}"
            amazon_provided = bool(
                cidr_obj.ipam_pool_id is None and cidr_obj.cidr is None
            )
            nbg = (
                self.region
                if (cidr_obj.ipam_pool_id is None and cidr_obj.cidr is None)
                else None
            )
            size = cidr_obj.size if cidr_obj.ipam_pool_id is not None else None
            ipv6_cidr = awscc.ec2.VpcCidrBlock(
                name,
                vpc_id=self.vpc.id,
                cidr_block=str(cidr_obj.cidr) if cidr_obj.cidr else None,
                ipv6_ipam_pool_id=cidr_obj.ipam_pool_id,
                ipv6_netmask_length=size,
                amazon_provided_ipv6_cidr_block=amazon_provided,
                ipv6_cidr_block_network_border_group=nbg,
                opts=ResourceOptions(parent=self.vpc),
            )
            ipv6_cidr_associations.append(ipv6_cidr)
        return ipv6_cidr_associations

    def _create_subnets(
        self,
        config: VPCConfig,
    ) -> dict[str, aws.ec2.Subnet]:
        class SubnetAutoAllocateCidr(TypedDict):
            ipv4: Output[str]
            ipv6: Output[str]

        # group subnets by cidr num preserving order
        grouped_subnets = GroupedSubnets(ipv4=defaultdict(list), ipv6=defaultdict(list))
        for subnet_cfg in config.subnets:
            if subnet_cfg.ipv4:
                grouped_subnets["ipv4"][subnet_cfg.ipv4.cidr_num].append(subnet_cfg)
            if subnet_cfg.ipv6:
                grouped_subnets["ipv6"][subnet_cfg.ipv6.cidr_num].append(subnet_cfg)

        subnet_name_to_cidrs = defaultdict(SubnetAutoAllocateCidr)
        cidr_assoc_mapping = {
            "ipv4": self.ipv4_cidr_associations,
            "ipv6": self.ipv6_cidr_associations,
        }
        cidr_block_mapping = {
            "ipv4": "cidr_block",
            "ipv6": "ipv6_cidr_block",
        }

        for ip_version, groups in grouped_subnets.items():
            for cidr_num, subnets in groups.items():
                subnets_auto_allocate = [
                    (subnet.name, getattr(subnet, ip_version).size)
                    for subnet in subnets
                    if not getattr(subnet, ip_version).cidr
                ]
                if not subnets_auto_allocate:
                    continue

                cidr_block = getattr(
                    cidr_assoc_mapping[ip_version][cidr_num - 1],
                    cidr_block_mapping[ip_version],
                )
                allocated_subnets = cidr_block.apply(
                    lambda cidr,
                    subnets=subnets_auto_allocate: divide_supernet_into_subnets(
                        cidr, [s[1] for s in subnets]
                    )
                )
                for i, (subnet_name, _) in enumerate(subnets_auto_allocate):
                    subnet_name_to_cidrs[subnet_name][ip_version] = (
                        allocated_subnets.apply(lambda cidrs, i=i: cidrs[i])
                    )
                    # def f(cidrs, i=i):
                    #     pulumi.log.info(cidrs[i])
                    #     return cidrs[i]

                    # pulumi.log.info(subnet_name)
                    # subnet_name_to_cidrs[subnet_name][ip_version] = (
                    #     allocated_subnets.apply(f)
                    # )

        name_to_subnet = {}
        az_id_prefix = VPC.get_az_id_prefix()
        for subnet_cfg in config.subnets:
            dependencies = []
            subnet_cidrs = SubnetCidrs(ipv4=None, ipv6=None)
            for ip_version in ["ipv4", "ipv6"]:
                cidr_cfg = getattr(subnet_cfg, ip_version)
                if cidr_cfg:
                    dependencies.append(
                        cidr_assoc_mapping[ip_version][cidr_cfg.cidr_num - 1]
                    )
                    cidr = cidr_cfg.cidr
                    if cidr:
                        subnet_cidrs[ip_version] = cidr
                    else:
                        subnet_cidrs[ip_version] = subnet_name_to_cidrs[
                            subnet_cfg.name
                        ][ip_version]

            # Complete AZ id
            if type(subnet_cfg.az_id) is int:
                az_id = f"{az_id_prefix}{subnet_cfg.az_id}"
            else:
                az_id = subnet_cfg.az_id

            subnet = awscc.ec2.Subnet(
                subnet_cfg.name,
                vpc_id=self.vpc.id,
                availability_zone_id=az_id,
                cidr_block=subnet_cidrs["ipv4"],
                ipv6_cidr_block=subnet_cidrs["ipv6"],
                ipv6_native=bool(subnet_cidrs["ipv6"] and not subnet_cidrs["ipv4"]),
                assign_ipv6_address_on_creation=bool(subnet_cidrs["ipv6"]),
                enable_dns64=bool(subnet_cidrs["ipv6"]),
                tags=VPC.build_tags(
                    config.common_tags,
                    subnet_cfg.tags,
                    Name=f"{config.name}-{subnet_cfg.name}",
                ),
                opts=ResourceOptions(
                    depends_on=dependencies,
                    parent=self.vpc,
                    delete_before_replace=True,
                ),
            )
            name_to_subnet[subnet_cfg.name] = SubnetInfo(
                subnet=subnet, route_table=subnet_cfg.route_table
            )
        return name_to_subnet

    # def _create_elastic_ips(self, config: VPCConfig) -> dict[str, aws.ec2.Eip]:
    #     result = {}
    #     for eip_config in config.elastic_ips:
    #         eip = aws.ec2.Eip(
    #             eip_config.name,
    #             **eip_config.dump(),
    #             tags=VPC.build_tags(
    #                 config.common_tags, eip_config.tags, Name=eip_config.name
    #             ),
    #             opts=ResourceOptions(parent=self),
    #         )
    #         result[eip_config.name] = eip
    #     return result

    # @staticmethod
    # def _create_nat_gateways(
    #     config: VPCConfig,
    #     subnets: dict[str, SubnetInfo],
    #     elastic_ips: dict[str, aws.ec2.Eip],
    # ) -> dict[str, aws.ec2.NatGateway]:
    #     result = {}
    #     for nat_config in config.nat_gateways:
    #         primary_eip_id = None
    #         if nat_config.is_public:
    #             primary_eip_id = elastic_ips[nat_config.eips[0]].id
    #         tags = VPC.build_tags(
    #             config.common_tags,
    #             nat_config.tags,
    #             Name=f"{config.name}_{nat_config.name}",
    #         )
    #         subnet = subnets[nat_config.subnet].subnet
    #         nat_gw = aws.ec2.NatGateway(
    #             nat_config.name,
    #             subnet_id=subnet.id,
    #             connectivity_type=nat_config.type.value,
    #             allocation_id=primary_eip_id,
    #             secondary_allocation_ids=[
    #                 elastic_ips[eip].id for eip in nat_config.eips[1:]
    #             ],
    #             tags=tags,
    #             opts=ResourceOptions(parent=subnet),
    #         )
    #         result[nat_config.name] = nat_gw
    #     return result

    def _create_route_tables(
        self,
        config: VPCConfig,
    ) -> dict[str, RouteTableInfo]:
        name_to_rt = {}
        for rt_config in config.route_tables:
            route_table = awscc.ec2.RouteTable(
                rt_config.name,
                vpc_id=self.vpc.vpc_id,
                tags=VPC.build_tags(
                    config.common_tags,
                    rt_config.tags,
                    Name=f"{config.name}-{rt_config.name}",
                ),
                **rt_config.extra_options,
                opts=ResourceOptions(parent=self.vpc),
            )

            routes = {}
            for route_cfg in rt_config.routes:
                dest_input, dest_id = self.parse_route_table_destination(
                    route_cfg.destination
                )
                next_hop = self.parse_route_table_next_hop(route_cfg.next_hop)
                route = awscc.ec2.Route(
                    f"{rt_config.name}_{dest_id}",
                    route_table_id=route_table.id,
                    **dest_input,
                    **next_hop,
                    opts=ResourceOptions(
                        parent=route_table,
                        delete_before_replace=True,
                        replace_on_changes=["*"],
                    ),
                )
                routes[route_cfg.destination] = route
            name_to_rt[rt_config.name] = RouteTableInfo(rt=route_table, routes=routes)
        return name_to_rt

    def parse_route_table_destination(
        self, destination: str
    ) -> tuple[dict[str, str], str]:
        dest_id = destination
        if destination.startswith("pl-"):
            dest_input = {"destination_prefix_list_id": destination}
        elif destination.startswith("subnet@"):
            match = re.match(r"subnet\@(?P<subnet>[\w\-]+)\.(?P<attr>\w+)", destination)
            if not match:
                raise ValueError(f"Can't parse destination: {destination}")
            subnet_name = match.group("subnet")
            ip_version = match.group("attr")
            dest_id = f"{subnet_name}.{ip_version}"
            subnet = self.subnets[subnet_name].subnet
            if ip_version == "ipv4":
                dest_input = {"destination_cidr_block": subnet.cidr_block}
            elif ip_version == "ipv6":
                dest_input = {"destination_ipv6_cidr_block": subnet.ipv6_cidr_block}
            else:
                raise ValueError(f"Unknown IP version: {ip_version}")
        elif isinstance(ip_network(destination), IPv4Network):
            dest_input = {"destination_cidr_block": destination}
        elif isinstance(ip_network(destination), IPv6Network):
            dest_input = {"destination_ipv6_cidr_block": destination}
        else:
            raise ValueError(f"Unknown destination: {destination}")
        return dest_input, dest_id

    def parse_route_table_next_hop(self, next_hop: str) -> dict[str, str | Output[str]]:
        if next_hop == "vgw":
            if self.virtual_private_gateway is None:
                raise ValueError("No Virtual Gateway has been created")
            next_hop = {"gateway_id": self.virtual_private_gateway.vgw.id}
        elif next_hop.startswith("vgw-"):
            next_hop = {"gateway_id": next_hop}
        elif next_hop == "igw":
            if self.internet_gateway is None:
                raise ValueError("No Internet Gateway has been created")
            next_hop = {"gateway_id": self.internet_gateway.igw.id}
        elif next_hop.startswith("igw-"):
            next_hop = {"gateway_id": next_hop}
        elif next_hop == "eigw":
            if self.egress_only_igw is None:
                raise ValueError("No Egress-Only Internet Gateway has been created")
            next_hop = {"egress_only_internet_gateway_id": self.egress_only_igw.id}
        elif next_hop.startswith("eigw-"):
            next_hop = {"egress_only_internet_gateway_id": next_hop}
        elif next_hop.startswith("eni-"):
            next_hop = {"network_interface_id": next_hop}
        elif next_hop.startswith("tgw-"):
            next_hop = {"transit_gateway_id": next_hop}
        elif next_hop.startswith("pcx-"):
            next_hop = {"vpc_peering_connection_id": next_hop}
        elif next_hop.startswith("pcx@"):
            ref = next_hop.removeprefix("pcx@")
            if ref.startswith("ssm:"):
                pcx_id = awscc.get_ssm_parameter_string_output(
                    name=ref.removeprefix("ssm:")
                ).value
            else:
                tags = {}
                args = {}
                for s in ref.split(","):
                    k, _, v = s.partition("=")
                    if k.startswith("tag:"):
                        tags[k.removeprefix("tag:")] = v
                    else:
                        args[k] = v

                pcx_id = aws.ec2.get_vpc_peering_connection_output(
                    tags=tags if tags else None, **args
                ).id
            next_hop = {"vpc_peering_connection_id": pcx_id}
        elif "core-network" in next_hop:
            next_hop = {"core_network_arn": next_hop}
        else:
            raise ValueError(f"Unknown next hop: {next_hop}")
        return next_hop

    def _create_route_table_associations(
        self,
    ) -> RouteTableAssociations:
        subnets_assoc = {}
        igw_assoc = None
        vgw_assoc = None
        for subnet_name, subnet_info in self.subnets.items():
            rt_name = subnet_info.route_table
            if rt_name is None:
                continue
            rt_id = self.route_tables[rt_name].rt.id
            association = awscc.ec2.SubnetRouteTableAssociation(
                f"{subnet_name}_{rt_name}",
                route_table_id=rt_id,
                subnet_id=subnet_info.subnet.id,
                opts=ResourceOptions(parent=subnet_info.subnet),
            )
            subnets_assoc[subnet_name] = association

        if self.internet_gateway.rt is not None:
            igw_assoc = awscc.ec2.GatewayRouteTableAssociation(
                f"igw_{self.internet_gateway.rt}",
                route_table_id=self.route_tables[self.internet_gateway.rt].rt.id,
                gateway_id=self.internet_gateway.igw.id,
                opts=ResourceOptions(parent=self.internet_gateway.igw),
            )

        if self.virtual_private_gateway.rt is not None:
            vgw_assoc = awscc.ec2.GatewayRouteTableAssociation(
                f"vgw_{self.virtual_private_gateway.rt}",
                route_table_id=self.route_tables[self.virtual_private_gateway.rt].rt.id,
                gateway_id=self.virtual_private_gateway.vgw.id,
                opts=ResourceOptions(parent=self.virtual_private_gateway.vgw),
            )

        return RouteTableAssociations(
            subnets=subnets_assoc,
            igw=igw_assoc,
            vgw=vgw_assoc,
        )

    def _create_internet_gateway(self, config: VPCConfig) -> InternetGatewayInfo:
        if config.internet_gateway is None:
            return InternetGatewayInfo(igw=None, rt=None, attachment=None)
        igw = awscc.ec2.InternetGateway(
            "igw",
            tags=VPC.build_tags(
                config.common_tags,
                config.internet_gateway.tags,
                Name=f"{config.name}-igw",
            ),
            **config.internet_gateway.extra_args,
            opts=ResourceOptions(parent=self.vpc),
        )
        attachment = awscc.ec2.VpcGatewayAttachment(
            "igw",
            opts=ResourceOptions(parent=igw),
            vpc_id=self.vpc.id,
            internet_gateway_id=igw.id,
        )
        return InternetGatewayInfo(
            igw=igw, rt=config.internet_gateway.route_table, attachment=attachment.id
        )

    def _create_virtual_private_gateway(
        self, config: VPCConfig
    ) -> VirtualPrivateGatewayInfo:
        if config.virtual_private_gateway is None:
            return VirtualPrivateGatewayInfo(vgw=None, rt=None, attachment=None)
        vgw = awscc.ec2.VpnGateway(
            "vgw",
            tags=VPC.build_tags(
                config.common_tags,
                config.virtual_private_gateway.tags,
                Name=f"{config.name}-vgw",
            ),
            amazon_side_asn=config.virtual_private_gateway.asn,
            type="ipsec.1",
            **config.virtual_private_gateway.extra_args,
            opts=ResourceOptions(
                parent=self.vpc,
                delete_before_replace=True,
            ),
        )
        attachment = awscc.ec2.VpcGatewayAttachment(
            "vgw",
            opts=ResourceOptions(
                parent=vgw,
                delete_before_replace=True,
                depends_on=[vgw],
            ),
            vpc_id=self.vpc.id,
            vpn_gateway_id=vgw.id,
        )
        return VirtualPrivateGatewayInfo(
            vgw=vgw,
            rt=config.virtual_private_gateway.route_table,
            attachment=attachment.id,
        )

    def _create_egress_only_igw(
        self, config: VPCConfig
    ) -> awscc.ec2.EgressOnlyInternetGateway | None:
        if config.egress_only_internet_gateway is None:
            return None
        eigw = awscc.ec2.EgressOnlyInternetGateway(
            "eigw",
            vpc_id=self.vpc.id,
            **config.egress_only_internet_gateway.extra_args,
            opts=ResourceOptions(parent=self.vpc),
        )
        return eigw

    # @staticmethod
    # def _create_attachments(
    #     config: VPCConfig, subnets: dict[str, SubnetInfo], vpc: aws.ec2.Vpc
    # ) -> dict[
    #     str,
    #     AttachmentInfo,
    # ]:
    #     attachments = {}
    #     for att_config in config.attachments:
    #         tags = VPC.build_tags(
    #             config.common_tags,
    #             att_config.tags,
    #             Name=f"{config.name}-vpc-attachment",
    #         )
    #         if att_config.type is AttachmentType.TRANSIT_GATEWAY:
    #             attachment = aws.ec2transitgateway.VpcAttachment(
    #                 att_config.name,
    #                 transit_gateway_id=att_config.tgw_id,
    #                 vpc_id=vpc.id,
    #                 subnet_ids=[
    #                     subnets[subnet_name].subnet.id
    #                     for subnet_name in att_config.subnets
    #                 ],
    #                 tags=tags,
    #                 opts=ResourceOptions(parent=vpc),
    #             )
    #             # TODO: association and propagation cross account
    #             # use opts=ResourceOptions(provider=provider)
    #             association = None
    #             if att_config.association_rt:
    #                 association = aws.ec2transitgateway.RouteTableAssociation(
    #                     f"{att_config.association_rt}_association",
    #                     transit_gateway_attachment_id=attachment.id,
    #                     transit_gateway_route_table_id=att_config.association_rt,
    #                     opts=ResourceOptions(parent=attachment),
    #                 )
    #             propagations = [
    #                 aws.ec2transitgateway.RouteTablePropagation(
    #                     f"{propagation_rt}_propagation",
    #                     transit_gateway_attachment_id=attachment.id,
    #                     transit_gateway_route_table_id=propagation_rt,
    #                     opts=ResourceOptions(parent=attachment),
    #                 )
    #                 for propagation_rt in att_config.propagation_rts
    #             ]
    #             attachments[att_config.name] = AttachmentInfo(
    #                 type=AttachmentType.TRANSIT_GATEWAY,
    #                 attachment=attachment,
    #                 association=association,
    #                 propagations=propagations,
    #                 tgw_id=att_config.tgw_id,
    #             )

    #         elif att_config.type is AttachmentType.CLOUDWAN:
    #             attachment = aws.networkmanager.VpcAttachment(
    #                 att_config.name,
    #                 core_network_id=att_config.core_network_id,
    #                 subnet_arns=[
    #                     subnets[subnet_name].subnet.arn
    #                     for subnet_name in att_config.subnets
    #                 ],
    #                 vpc_arn=vpc.arn,
    #                 tags=tags,
    #                 opts=ResourceOptions(parent=vpc),
    #             )
    #             attachments[att_config.name] = AttachmentInfo(
    #                 type=AttachmentType.CLOUDWAN,
    #                 attachment=attachment,
    #                 core_network_id=att_config.core_network_id,
    #             )
    #     return attachments

    def _create_endpoints(self, config: VPCConfig) -> dict[str, Any]:
        endpoints = {}
        for vpce in self.config.endpoints:
            service = vpce.service
            if "." not in service:
                service = f"com.amazonaws.{self.region}.{service}"
            rt_ids = [self.route_tables[rt].rt.id for rt in vpce.route_tables]
            endpoint = awscc.ec2.VpcEndpoint(
                vpce.name,
                vpc_id=self.vpc.id,
                service_name=service,
                route_table_ids=rt_ids,
                private_dns_enabled=vpce.private_dns,
                tags=VPC.build_tags(
                    config.common_tags,
                    vpce.tags,
                    Name=f"{config.name}_{vpce.name}",
                ),
                **vpce.extra_args,
                opts=ResourceOptions(parent=self.vpc),
            )
            endpoints[vpce.name] = endpoint
        return endpoints

    @staticmethod
    def build_tags(
        common_tags: dict[str, str],
        tags: dict[str, str],
        format: TagType = "aws",
        **kwargs: str,
    ) -> dict[str, str] | list[dict[str, str]]:
        tags = {**common_tags, **kwargs, **tags}
        if format == "aws":
            return [{"key": k, "value": v} for k, v in tags.items()]
        elif format == "dict":
            return tags
        else:
            raise ValueError(f"Invalid format: {format}")

    @property
    def vpc_id(self) -> Output[str]:
        return self.vpc.id

    @property
    def cidrs(self) -> VPCCidrs:
        return {
            "ipv4": [self.vpc.cidr_block]
            + [
                cidr_association.cidr_block
                for cidr_association in self.ipv4_cidr_associations
            ],
            "ipv6": [
                cidr_association.ipv6_cidr_block
                for cidr_association in self.ipv6_cidr_associations
            ],
        }

    # @property
    # def vgw_id(self) -> Optional[Output[str]]:
    #     if self.virtual_gateway is None:
    #         return None
    #     return self.virtual_gateway.vgw.id

    # @property
    # def igw_id(self) -> Optional[Output[str]]:
    #     if self.internet_gateway is None:
    #         return None
    #     return self.internet_gateway.igw.id

    @property
    def outputs(self) -> dict[str, Any]:
        result = {"id": self.vpc.id}
        return result
