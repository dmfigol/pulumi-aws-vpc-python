from pulumi_aws_vpc import VPC
import pulumi


def main():
    vpc_config = pulumi.Config().get_object("aws_vpc")
    vpc = VPC("vpc", config=vpc_config)
    pulumi.export("vpc_id", vpc.id)


if __name__ == "__main__":
    main()
