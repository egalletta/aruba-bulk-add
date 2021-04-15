#!/usr/bin/env python3

import paramiko
import getpass
from typing import Tuple

MANAGEMENT_IP = None


def login() -> Tuple[str, str]:
    username = input("Enter your username:\n> ")
    password = getpass.getpass("Enter your password:\n> ")
    return username, password


def setup_ssh(uname: str, pword: str) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(hostname=MANAGEMENT_IP, username=uname, password=pword)
    print("SSH Connection successfully established")
    return client


def str_grouper(n, iterable):
    args = [iter(iterable)] * n
    for part in zip(*args):
        yield "".join(part)


def convert_mac(mac: str) -> str:
    if ":" in mac:
        return mac
    return ":".join(str_grouper(2, mac.lower()))


def print_stream(s) -> str:
    res = ""
    for line in iter(s.readline, ""):
        res += line
        print(line, end="")
    return res


if __name__ == "__main__":

    if MANAGEMENT_IP == None:
        print(
            "No IP address set.\nPlease set Aruba Management IP in line 7\n\n\tExample: MANAGEMENT_IP = '10.0.0.1'"
        )
        exit(1)
    username, password = login()

    client = setup_ssh(username, password)

    while True:
        group = input("Enter the group name for the set of AP's to be added:\n> ")
        if group.lower() == "exit":
            break
        mac = input(
            "Enter the MAC address of the AP, or type 'exit' to "
            "return to group selection\n> "
        )
        while mac.lower() != "exit":
            mac = convert_mac(mac)
            ap_name = input(
                f"Enter the AP name for {mac}, or type "
                "'exit' to return to group selection\n> "
            )
            if ap_name.lower() == "exit":
                break
            elif ap_name.lower() == "back":
                mac = input(
                    "Enter the MAC address of the AP, or type 'exit' to "
                    "return to group selection\n> "
                )
                continue
            print(f"Setting device {mac} to name {ap_name} with group {group}...")

            # Verify AP is found:
            cmd = f"show ap database long | include {mac}"
            stdin, stdout, stderr = client.exec_command(cmd, get_pty=True)
            stdout_s = print_stream(stdout)
            if mac not in stdout_s:
                print("ERROR: MAC address not found- is the AP online?")
            else:
                # Set the AP name
                cmd = f"ap-rename wired-mac {mac} {ap_name}"
                stdin, stdout, stderr = client.exec_command(cmd, get_pty=True)
                print_stream(stdout)

                # Set the AP group
                cmd = f"ap-regroup wired-mac {mac} {group}"
                stdin, stdout, stderr = client.exec_command(cmd, get_pty=True)
                print_stream(stdout)

                print("Done!")

            mac = input(
                "Enter the MAC address of the AP, or type 'exit' to "
                "return to group selection\n> "
            )
