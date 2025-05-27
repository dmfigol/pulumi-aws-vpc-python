from pulumi.provider.experimental import component_provider_host

from pulumi_aws_vpc import VPC

if __name__ == "__main__":
    component_provider_host(
        components=[VPC],
        name="aws-networking",
    )
