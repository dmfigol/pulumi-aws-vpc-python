from typing import Any, TypedDict, Literal
from pulumi import Input
from typing import Optional


class SubnetCidrArgs(TypedDict):
    cidr_num: Optional[Input[int]]
    cidr: Optional[Input[str]]
    size: Optional[Input[int]]


class SubnetArgs(TypedDict):
    name: Input[str]
    az_id: Input[str]
    ipv4: Optional[SubnetCidrArgs]
    ipv6: Optional[SubnetCidrArgs]
    route_table: Optional[Input[str]]
    tags: Optional[dict[str, Input[str]]]
    extra_options: Optional[dict[str, Input[Any]]]


class VPCCidrArgs(TypedDict):
    cidr: Optional[Input[str]]
    size: Optional[Input[str]]
    ipam_pool_id: Optional[Input[str]]


class VPCCidrsArgs(TypedDict):
    ipv4: list[VPCCidrArgs]
    ipv6: Optional[list[VPCCidrArgs]]


class InternetGatewayArgs(TypedDict):
    tags: Optional[dict[str, Input[str]]]
    route_table: Optional[Input[str]]
    extra_options: Optional[dict[str, Input[Any]]]


class VirtualPrivateGatewayArgs(TypedDict):
    asn: Optional[Input[int]]
    tags: Optional[dict[str, Input[str]]]
    route_table: Optional[Input[str]]
    extra_options: Optional[dict[str, Input[Any]]]


class EgressOnlyInternetGatewayArgs(TypedDict):
    tags: Optional[dict[str, Input[str]]]
    extra_options: Optional[dict[str, Input[Any]]]


class RouteArgs(TypedDict):
    destination: Input[str]
    next_hop: Input[str]


class RouteTableArgs(TypedDict):
    name: Input[str]
    routes: Optional[list[RouteArgs]]
    tags: Optional[dict[str, Input[str]]]
    extra_options: Optional[dict[str, Input[Any]]]


VPCEndpointType = Literal[
    "Gateway", "Interface", "GatewayLoadBalancer", "Resource", "ServiceNetwork"
]


class VPCEndpointArgs(TypedDict):
    name: Input[str]
    service: Input[str]
    type: Input[str]
    route_tables: Optional[list[Input[str]]]
    tags: Optional[dict[str, Input[str]]]
    extra_options: Optional[dict[str, Input[Any]]]


class VPCArgs(TypedDict):
    name: Input[str]
    cidrs: VPCCidrsArgs
    subnets: Optional[list[SubnetArgs]]
    internet_gateway: Optional[InternetGatewayArgs]
    virtual_private_gateway: Optional[VirtualPrivateGatewayArgs]
    egress_only_internet_gateway: Optional[EgressOnlyInternetGatewayArgs]
    route_tables: Optional[list[RouteTableArgs]]
    endpoints: Optional[list[VPCEndpointArgs]]
    tags: Optional[dict[str, Input[str]]]
    common_tags: Optional[dict[str, Input[str]]]
    extra_options: Optional[dict[str, Input[Any]]]
