import netaddr


def divide_supernet_into_subnets(supernet: str, prefix_lengths: list[int]) -> list[str]:
    """Divide a supernet into subnets of arbitrary prefix lengths.

    Uses smart allocation of subnets using gaps between allocated blocks.

    Args:
        supernet: The supernet to divide.
        prefix_lengths: The prefix lengths to divide the supernet into.

    Returns:
        A list of subnets.

    Examples:
    >>> divide_supernet_into_subnets("10.10.10.0/24", [26, 25, 26])
    ['10.10.10.0/26', '10.10.10.128/25', '10.10.10.64/26']
    >>> divide_supernet_into_subnets("10.10.10.0/24", [26, 25, 27, 27])
    ['10.10.10.0/26', '10.10.10.128/25', '10.10.10.64/27', '10.10.10.96/27']

    In comparison with Terraform cidrsubnets function:
    > cidrsubnets("10.10.10.0/24", [2, 2, 1])
    tolist(["10.10.10.0/26", "10.10.10.64/26", "10.10.10.128/25"])
    > cidrsubnets("10.10.10.0/24", [2, 1, 2])
    Error: Invalid function argument
    """
    subnets = []
    free_blocks = [netaddr.IPNetwork(supernet)]
    for prefix in prefix_lengths:
        if not free_blocks:
            raise ValueError("No free blocks left to allocate")

        for i, current_block in enumerate(free_blocks):
            if prefix < current_block.prefixlen:
                # Can't create subnet larger than parent
                continue

            subnet = next(current_block.subnet(prefix))
            subnets.append(str(subnet))
            free_blocks = (
                free_blocks[:i]
                + netaddr.cidr_exclude(current_block, subnet)
                + free_blocks[i + 1 :]
            )
            free_blocks = netaddr.cidr_merge(free_blocks)
            break

    return subnets
