import pydantic
from pydantic import ConfigDict, model_validator, Field
from pydantic.networks import IPv4Address
from enum import Enum
from typing import Optional, Any
from typing_extensions import Self

from pulumi_aws_vpc.utils import divide_supernet_into_subnets


class BaseModel(pydantic.BaseModel):
    model_config = ConfigDict(extra="forbid", coerce_numbers_to_str=True)


class Subnet(BaseModel):
    name: str
    az_id: str
    cidr: Optional[str] = None
    prefix_length: Optional[int] = None
    route_table: Optional[str] = None
    tags: dict[str, str] = {}


class VPCCidr(BaseModel):
    cidr: str
    subnets: list[Subnet]

    def get_subnets(self) -> list[Subnet]:
        auto_allocate_subnets = [
            subnet
            for subnet in self.subnets
            if subnet.prefix_length and not subnet.cidr
        ]
        if auto_allocate_subnets:
            cidrs = divide_supernet_into_subnets(
                self.cidr, [subnet.prefix_length for subnet in auto_allocate_subnets]
            )
            for cidr, subnet in zip(cidrs, auto_allocate_subnets):
                subnet.cidr = cidr
        return self.subnets


class Route(BaseModel):
    destination: str
    next_hop: str


class RouteTable(BaseModel):
    name: str
    routes: list[Route]
    tags: dict[str, str] = {}


class VirtualGateway(BaseModel):
    asn: int
    route_table: Optional[str] = None
    tags: dict[str, str] = {}
    vpn_connections: list[Any] = []


class InternetGateway(BaseModel):
    route_table: str
    tags: dict[str, str] = {}


class ElasticIP(BaseModel):
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


class VPCAttachment(BaseModel):
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


class NATGateway(BaseModel):
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


class VPCConfig(BaseModel):
    name: str
    internet_gateway: Optional[InternetGateway] = None
    virtual_gateway: Optional[VirtualGateway] = None
    elastic_ips: list[ElasticIP] = []
    cidrs: list[VPCCidr]
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
        return self.cidrs[0]

    @property
    def secondary_cidrs(self) -> list[VPCCidr]:
        if len(self.cidrs) < 2:
            raise ValueError(f"VPC {self.name} has only {len(self.cidrs)} CIDRs")
        return self.cidrs[1:]
