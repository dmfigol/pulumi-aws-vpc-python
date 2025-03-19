from pulumi import Input
from typing import Optional, TypedDict


class VPCIPv4CidrArgs(TypedDict):
    cidr: Optional[str] = None
    size: Optional[int] = None
    ipam_pool: Optional[str] = None


class VPCIPv6CidrArgs(TypedDict):
    cidr: Optional[str] = None
    size: Optional[int] = 56
    ipam_pool: Optional[str] = None


class SubnetIPv4CidrArgs(TypedDict, total=False):
    cidr_num: int = 1
    cidr: Optional[str] = None
    size: Optional[int] = None


class SubnetIPv6CidrArgs(TypedDict, total=False):
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
    tags: Input[dict[str, str]]
    common_tags: Input[dict[str, str]]

    @property
    def primary_cidr(self) -> VPCIPv4CidrArgs:
        return self.cidrs.ipv4[0]