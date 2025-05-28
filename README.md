# Pulumi cross-language AWS VPC component

Advanced Pulumi cross-language component written in Python to build a well-architected Amazon VPC that supports a wide range of related resources.

## Supported features
- Amazon Virtual Private Cloud, subnets, route tables
  - automatic cidr allocation for subnets is supported
  - references to other resources in the route table are supported
- Elastic IPs and NAT Gateways
- Internet Gateway and Virtual Private Gateway
- Transit Gateway and Cloud WAN attachments
- Route 53 Profiles [WIP]
- Flow Logs [WIP]
- IPv6 [WIP]
- Endpoints [WIP]


### Configuration
YAML example is below:
```yaml
name: pulumi-aws-vpc-stacks
description: Pulumi VPC stacks deployed with YAML
runtime: yaml
plugins:
  providers:
    - name: aws-networking
      path: ../../
resources:
  vpc:
    type: aws-networking:index:VPC
    properties:
    config:
      name: "pulumi-yaml"
      cidrs:
        ipv4:
          - cidr: 10.20.0.0/16
          - cidr: 100.64.0.0/26
        ipv6:
          - {}  # amazon provided, default size is 56
          - {size: 56}  # amazon provided
      subnets:
        - {name: int-az1, azId: euc1-az1, ipv4: {size: 24}, ipv6: {}, routeTable: private, tags: {"my-subnet-tag": "test"}}
        - {name: int-az2, azId: euc1-az1, ipv4: {size: 24}, ipv6: {}, routeTable: private}
        - {name: ext-az1, azId: 1, ipv4: {size: 25}, ipv6: {}, routeTable: public}  # azId: 1 is the same as euc1-az1
        - {name: ext-az2, azId: 2, ipv4: {size: 25}, ipv6: {}, routeTable: public}
        - {name: ipv6only-az1, azId: 1, ipv6: {}, routeTable: private}
        - {name: ipv6only-az2, azId: 2, ipv6: {}, routeTable: private}
        - {name: attach-az1, azId: 1, ipv4: {cidr: "100.64.0.0/28", cidrNum: 2}, ipv6: {cidrNum: 2}}
        - {name: attach-az2, azId: 2, ipv4: {cidr: "100.64.0.16/28", cidrNum: 2}, ipv6: {cidrNum: 2}}
      internetGateway:
        tags: {"TestIgwTag": "TestIgwValue"}
        routeTable: ingress
      virtualPrivateGateway:
        asn: 65500
        tags: {"TestVGWTag": "TestVGWValue"}
        # routeTable: ingress
      egressOnlyInternetGateway:
        tags: {"TestEigwTag": "TestEigwValue"}  # EIGW tags are not yet implemented in CloudFormation Resource Provider
      routeTables:
        - name: private
          tags: {"TestRtTag": "TestRtValue"}
          routes:
            - destination: 0.0.0.0/0
              nextHop: igw
            - destination: ::/0
              nextHop: eigw
        - name: public
          routes:
            - destination: 0.0.0.0/0
              nextHop: igw
            - destination: ::/0
              nextHop: igw
        - name: test
          routes:
            - destination: 1.2.3.4/32
              nextHop: igw
            # - destination: 4.3.2.1/32
            #   nextHop: attachment@tgw
            - destination: 10.30.0.0/24
              nextHop: pcx@tag:Name=MyPeering,tag:Environment=dev
            - destination: 10.40.0.0/24
              nextHop: pcx@ssm:/my-peering/id 
        - name: ingress
          routes:
            - destination: subnet@ext-az1.ipv4
              nextHop: eni-0ff40dc93d3cc702f
            - destination: subnet@ext-az1.ipv6
              nextHop: eni-0ff40dc93d3cc702f
              # nextHop: endpoint@fw-az1
      endpoints:
        - {name: "s3", service: "s3", type: "Gateway", routeTables: ["private", "public"]}  # or com.amazonaws.eu-central-1.s3
outputs:
  vpcId: ${vpc.vpcId}
```