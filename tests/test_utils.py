from pulumi_aws_vpc.utils import divide_supernet_into_subnets
import pytest


@pytest.mark.parametrize(
    "supernet, prefix_lengths, expected",
    [
        (
            "10.10.10.0/24",
            [26, 25, 26],
            ["10.10.10.0/26", "10.10.10.128/25", "10.10.10.64/26"],
        ),
        (
            "10.10.10.0/24",
            [26, 25, 27, 27],
            ["10.10.10.0/26", "10.10.10.128/25", "10.10.10.64/27", "10.10.10.96/27"],
        ),
        (
            "10.10.10.0/24",
            [],
            [],
        ),
        (
            "2001:db8::/48",
            [64, 64, 64, 64],
            [
                "2001:db8::/64",
                "2001:db8:0:1::/64",
                "2001:db8:0:2::/64",
                "2001:db8:0:3::/64",
            ],
        ),
    ],
)
def test_divide_supernet_into_subnets(supernet, prefix_lengths, expected):
    assert divide_supernet_into_subnets(supernet, prefix_lengths) == expected
