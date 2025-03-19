from pulumi_aws_vpc import VPC


def main():
    vpc = VPC(name="my-vpc", cidr="10.0.0.0/16")
    print(vpc.name)


if __name__ == "__main__":
    main()
