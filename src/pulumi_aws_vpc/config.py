import pydantic
from pydantic import ConfigDict, model_validator, Field
from pydantic.networks import IPv4Address
from enum import Enum
from typing import Optional, Any
from typing_extensions import Self, TypedDict
from pulumi import Input, Output


class BaseModel(pydantic.BaseModel):
    model_config = ConfigDict(extra="forbid", coerce_numbers_to_str=True)


class CoreModel(pydantic.BaseModel):
    model_config = ConfigDict(extra="allow", coerce_numbers_to_str=True)


class IPv4SubnetCidr(BaseModel):
    cidr: Optional[str] = None
    cidr_num: int = 1
    size: Optional[int] = None


class IPv6SubnetCidr(BaseModel):
    cidr: Optional[str] = None
    cidr_num: int = 1
    size: Optional[int] = 64


class Subnet(CoreModel):
    name: str
    az_id: str
    ipv4: Optional[IPv4SubnetCidr] = None
    ipv6: Optional[IPv6SubnetCidr] = None
    route_table: Optional[str] = None
    tags: dict[str, str] = {}


class VPCCidr(BaseModel):
    cidr: Optional[str] = None
    size: Optional[int] = None
    ipam_pool: Optional[str] = None


class VPCCidrs(BaseModel):
    ipv4: list[VPCCidr]
    ipv6: list[VPCCidr]


class Route(BaseModel):
    destination: str
    next_hop: str


class RouteTable(CoreModel):
    name: str
    routes: list[Route]
    tags: dict[str, str] = {}


class VirtualGateway(CoreModel):
    asn: int
    route_table: Optional[str] = None
    tags: dict[str, str] = {}
    vpn_connections: list[Any] = []


class InternetGateway(CoreModel):
    route_table: str
    tags: dict[str, str] = {}


class ElasticIP(CoreModel):
    name: str
    border_group: Optional[str] = Field(
        None, serialization_alias="network_border_group"
    )
    public_pool: Optional[str] = Field(None, serialization_alias="public_ipv4_pool")
    customer_owned_pool: Optional[str] = Field(
        None, serialization_alias="customer_owned_ipv4_pool"
    )
    ipam_pool: Optional[str] = Field(None, serialization_alias="ipam_pool_id")
    ip: Optional[IPv4Address] = Field(None, serialization_alias="address")
    tags: dict[str, str] = {}

    def dump(self) -> dict[str, Any]:
        result = self.model_dump(
            mode="json", by_alias=True, exclude=["tags", "name"], exclude_none=True
        )
        return result


class AttachmentType(str, Enum):
    TRANSIT_GATEWAY = "transit_gateway"
    CLOUDWAN = "cloudwan"


class VPCAttachment(CoreModel):
    name: str
    type: AttachmentType
    subnets: list[str]
    tgw_id: Optional[str] = None
    core_network_id: Optional[str] = None
    provider: Optional[str] = None
    association_rt: Optional[str] = None
    propagation_rts: list[str] = []
    tags: dict[str, str] = {}


class NATGatewayType(str, Enum):
    PUBLIC = "public"
    PRIVATE = "private"


class NATGateway(CoreModel):
    name: str
    type: NATGatewayType = NATGatewayType.PUBLIC
    subnet: str
    eips: list[str] = []
    tags: dict[str, str] = {}

    @model_validator(mode="after")
    def validate_number_of_eips(self) -> Self:
        if self.type is NATGatewayType.PUBLIC:
            if not self.eips:
                raise ValueError("Public NAT Gateway must have at least one Elastic IP")
        elif self.type is NATGatewayType.PRIVATE:
            if self.eips:
                raise ValueError("Private NAT Gateway must not have Elastic IPs")
        return self

    @property
    def is_public(self) -> bool:
        return self.type is NATGatewayType.PUBLIC


class VPCConfig(CoreModel):
    name: str
    internet_gateway: Optional[InternetGateway] = None
    virtual_gateway: Optional[VirtualGateway] = None
    elastic_ips: list[ElasticIP] = []
    cidrs: VPCCidrs
    subnets: list[Subnet] = []
    route_tables: list[RouteTable]
    nat_gateways: list[NATGateway] = []
    attachments: list[VPCAttachment] = []
    endpoints: list[Any] = []
    dns: Any = None
    flow_logs: list[Any] = []
    tags: dict[str, str] = {}
    common_tags: dict[str, str] = {}

    @property
    def primary_cidr(self) -> VPCCidr:
        return self.cidrs.ipv4[0]


class VPCIPv4CidrArgs(TypedDict):
    cidr: Optional[str] = None
    size: Optional[int] = None
    ipam_pool: Optional[str] = None


class VPCIPv6CidrArgs(TypedDict):
    cidr: Optional[str] = None
    size: Optional[int] = 56
    ipam_pool: Optional[str] = None


class SubnetIPv4CidrArgs(TypedDict):
    cidr_num: int = 1
    cidr: Optional[str] = None
    size: Optional[int] = None


class SubnetIPv6CidrArgs(TypedDict):
    cidr_num: int = 1
    cidr: Optional[str] = None
    size: Optional[int] = 64


class SubnetArgs(TypedDict):
    name: str
    az_id: str
    ipv4: Optional[SubnetIPv4CidrArgs] = None
    ipv6: Optional[SubnetIPv6CidrArgs] = None
    route_table: Optional[str] = None
    tags: dict[str, str] = {}


class VPCCidrArgs(TypedDict):
    ipv4: list[VPCIPv4CidrArgs]
    ipv6: list[VPCIPv6CidrArgs]


class VPCArgs(TypedDict):
    name: Input[str]
    # cidr: Input[str]
    cidrs: Input[VPCCidrArgs]
    subnets: Input[list[SubnetArgs]]

    @property
    def primary_cidr(self) -> VPCCidr:
        return self.cidrs.ipv4[0]
