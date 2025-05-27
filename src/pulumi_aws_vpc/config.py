import pydantic
from pydantic import ConfigDict, model_validator, Field
from ipaddress import IPv4Address, IPv4Network, IPv6Network
from pydantic.alias_generators import to_snake
from typing import Any, Literal
from typing_extensions import Self
from pulumi_aws_vpc.errors import VPCConfigError


class BaseModel(pydantic.BaseModel):
    model_config = ConfigDict(extra="forbid", coerce_numbers_to_str=True)


class ApiResource(BaseModel):
    extra_options: dict[str, Any] = Field(default_factory=dict, exclude=True)
    tags: dict[str, str] = Field(default_factory=dict)

    @property
    def extra_args(self) -> dict[str, Any]:
        return {to_snake(k): v for k, v in self.extra_options.items()}

    @property
    def aws_tags(self) -> list[dict[str, str]]:
        return [{"key": k, "value": v} for k, v in self.tags.items()]


class SubnetIPv4Cidr(BaseModel):
    cidr_num: int = 1
    cidr: str | None = None
    size: int | None = None


class SubnetIPv6Cidr(BaseModel):
    cidr_num: int = 1
    cidr: str | None = None
    size: int = 64


class Subnet(ApiResource):
    name: str
    az_id: int | str
    ipv4: SubnetIPv4Cidr | None = None
    ipv6: SubnetIPv6Cidr | None = None
    route_table: str | None = None


# class VPCCidr(BaseModel):
#     cidr: str
#     subnets: list[Subnet]

#     def get_subnets(self) -> list[Subnet]:
#         auto_allocate_subnets = [
#             subnet
#             for subnet in self.subnets
#             if subnet.prefix_length and not subnet.cidr
#         ]
#         if auto_allocate_subnets:
#             cidrs = divide_supernet_into_subnets(
#                 self.cidr, [subnet.prefix_length for subnet in auto_allocate_subnets]
#             )
#             for cidr, subnet in zip(cidrs, auto_allocate_subnets):
#                 subnet.cidr = cidr
#         return self.subnets


class Route(BaseModel):
    destination: str
    next_hop: str


class RouteTable(ApiResource):
    name: str
    routes: list[Route]


class VirtualPrivateGateway(ApiResource):
    asn: int = 64512  # Amazon default ASN
    route_table: str | None = None
    vpn_connections: list[Any] = []


class InternetGateway(ApiResource):
    route_table: str | None = None


class EgressOnlyInternetGateway(ApiResource):
    route_table: str | None = None


class ElasticIP(ApiResource):
    name: str
    border_group: str | None = Field(None, serialization_alias="network_border_group")
    public_pool: str | None = Field(None, serialization_alias="public_ipv4_pool")
    customer_owned_pool: str | None = Field(
        None, serialization_alias="customer_owned_ipv4_pool"
    )
    ipam_pool: str | None = Field(None, serialization_alias="ipam_pool_id")
    ip: IPv4Address | None = Field(None, serialization_alias="address")

    # def dump(self) -> dict[str, Any]:
    #     result = self.model_dump(
    #         mode="json", by_alias=True, exclude="tags", "name", exclude_none=True
    #     )
    #     return result


# class AttachmentType(str, Enum):
#     TRANSIT_GATEWAY = "transit_gateway"
#     CLOUDWAN = "cloudwan"


# class VPCAttachment(BaseModel):
#     name: str
#     type: AttachmentType
#     subnets: list[str]
#     tgw_id: str | None = None
#     core_network_id: str | None = None
#     provider: str | None = None
#     association_rt: str | None = None
#     propagation_rts: list[str] = []
#     tags: dict[str, str] = {}


# class NATGatewayType(str, Enum):
#     PUBLIC = "public"
#     PRIVATE = "private"


# class NATGateway(BaseModel):
#     name: str
#     type: NATGatewayType = NATGatewayType.PUBLIC
#     subnet: str
#     eips: list[str] = []
#     tags: dict[str, str] = {}

#     @model_validator(mode="after")
#     def validate_number_of_eips(self) -> Self:
#         if self.type is NATGatewayType.PUBLIC:
#             if not self.eips:
#                 raise ValueError("Public NAT Gateway must have at least one Elastic IP")
#         elif self.type is NATGatewayType.PRIVATE:
#             if self.eips:
#                 raise ValueError("Private NAT Gateway must not have Elastic IPs")
#         return self

#     @property
#     def is_public(self) -> bool:
#         return self.type is NATGatewayType.PUBLIC


class IPv4VPCCidr(BaseModel):
    cidr: IPv4Network | None = None
    ipam_pool_id: str | None = None
    size: int | None = None


class IPv6VPCCidr(BaseModel):
    cidr: IPv6Network | None = None
    ipam_pool_id: str | None = None
    size: int | None = 56


class VPCCidrs(BaseModel):
    ipv4: list[IPv4VPCCidr] = []
    ipv6: list[IPv6VPCCidr] = []


VPCEndpointType = Literal[
    "Gateway", "Interface", "GatewayLoadBalancer", "Resource", "ServiceNetwork"
]


class VPCEndpoint(ApiResource):
    name: str
    service: str
    type: VPCEndpointType
    route_tables: list[str] = []
    subnets: list[str] | None = []
    security_groups: list[str] | None = []
    private_dns_enabled: bool | None = None

    @property
    def private_dns(self) -> bool:
        if self.private_dns_enabled is None:
            if self.type == "Interface":
                return True
            else:
                return False
        return self.private_dns_enabled


class VPCConfig(ApiResource):
    name: str
    cidrs: VPCCidrs
    common_tags: dict[str, str] = Field(default_factory=dict)
    subnets: list[Subnet] = []
    internet_gateway: InternetGateway | None = None
    virtual_private_gateway: VirtualPrivateGateway | None = None
    egress_only_internet_gateway: EgressOnlyInternetGateway | None = None
    # elastic_ips: list[ElasticIP] = []
    route_tables: list[RouteTable] = []
    # nat_gateways: list[NATGateway] = []
    # attachments: list[VPCAttachment] = []
    endpoints: list[VPCEndpoint] = []
    # dns: Any = None
    # flow_logs: list[Any] = []

    @property
    def primary_cidr(self) -> IPv4VPCCidr:
        return self.cidrs.ipv4[0]

    @property
    def secondary_ipv4_cidrs(self) -> list[IPv4VPCCidr]:
        return self.cidrs.ipv4[1:]

    @model_validator(mode="after")
    def check_route_tables_references(self) -> Self:
        route_tables = [rt.name for rt in self.route_tables]
        for subnet in self.subnets:
            if subnet.route_table and subnet.route_table not in route_tables:
                raise ValueError(
                    f"Subnet {subnet.name!r} references a route table {subnet.route_table!r} which is not defined"
                )
        if (
            self.internet_gateway
            and self.internet_gateway.route_table
            and self.internet_gateway.route_table not in route_tables
        ):
            raise ValueError(
                f"Internet Gateway references a route table {self.internet_gateway.route_table!r} which is not defined"
            )
        if (
            self.virtual_private_gateway
            and self.virtual_private_gateway.route_table
            and self.virtual_private_gateway.route_table not in route_tables
        ):
            raise ValueError(
                f"Virtual Private Gateway references a route table {self.virtual_private_gateway.route_table!r} which is not defined"
            )
        return self


# class VPCConfig(BaseModel):
#     name: str
#     cidr: str
#     tags: dict[str, str] = {}
