#!/usr/bin/env python3
from getpass import getpass
from urllib.parse import quote


def main() -> None:
    password = getpass("Redis password: ")
    print(quote(password, safe=""))


if __name__ == "__main__":
    main()
