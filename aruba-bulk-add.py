#!/usr/bin/env python3

import paramiko
import getpass
from typing import Tuple
import os
import csv
import sys
import time
import pprint

MANAGEMENT_IP = None


def login() -> (str, str):
    """
    Presents the login interface with non-echo password field
    :returns: tuple containing username, password
    """
    print(f"Logging in to {MANAGEMENT_IP}")
    username = input("Enter your username:\n> ")
    password = getpass.getpass("Enter your password:\n> ")
    return username, password


def setup_ssh(uname: str, pword: str) -> paramiko.SSHClient:
    """
    Logs into the host specied by the global MANAGEMENT_IP
    :param uname: username to authenticate with
    :param pword: password to authenticate with
    :returns: an authenticated SSH client.

    """
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(hostname=MANAGEMENT_IP, username=uname, password=pword)
    print("SSH Connection successfully established")
    return client


def str_grouper(n, iterable):
    """
    Assists in formatting mac addresses by splitting string into chunks of size n
    :param n: numbers of characters per chunk
    :param iterable: source string
    :returns: the string, group into size n chunks

    """
    args = [iter(iterable)] * n
    for part in zip(*args):
        yield "".join(part)


def convert_mac(mac: str) -> str:
    """
    Converts a potentially ill-formatted MAC address into a properly formatted one.
    :param mac: Potentially ill-formatted MAC address
    :returns:  Properly formatted MAC address

    """
    if ":" in mac:
        return mac
    return ":".join(str_grouper(2, mac.lower()))


def print_stream(s) -> str:
    """
    Prints a stream to stdout
    :param s: The input stream
    :returns: A string, containing the contents of the passed stream.

    """
    res = ""
    for line in iter(s.readline, ""):
        res += line
        print(line, end="")
    return res


def stream2str(s) -> str:
    """
    Converts a stream/file-like object to a string
    :param s: Stream to convert
    :returns: Stream in string form

    """

    res = ""
    for line in iter(s.readline, ""):
        res += line
    return res


def create_table(
    group: str, path: str, client: paramiko.SSHClient, interactive_mac
) -> None:
    """
    Appends AP's with the given group to the .csv file provied by the path.
    The AP's group, name, and empty field for MAC address will be appended.
    If the .csv file does not exist, a new one will be created wil appropriate headers.
    :param group: the AP group to append
    :param path: Path to the .csv file to append to
    :returns: None
    """
    if not os.path.isfile(path):
        with open(path, "w", newline="") as f:
            writer = csv.writer(f, delimiter=",")
            writer.writerow(["group", "name", "mac"])

    cmd = f"show ap database long group {group}"
    stdin, stdout, stderr = client.exec_command(cmd, get_pty=True)
    stdout_s = stream2str(stdout)

    aps = stdout_s.splitlines()
    for ap in aps:
        if len(ap) < 5 or ap[0:3] != "AP-":
            continue
        attrs = ap.split()
        name = attrs[0]
        # Remove "-OLD"/"old" suffixes on existing AP names
        if name[-4:].lower() == "-old":
            name = name[:-4]
        elif name[-3:].lower() == "old":
            name = name[:-3]
        with open(path, "a", newline="") as f:
            writer = csv.writer(f, delimiter=",")
            if interactive_mac:
                mac = input(f"Enter the MAC address for {name}:\n> ")
                writer.writerow([group, name, convert_mac(mac)])
            else:
                writer.writerow([group, name, ""])


def write_conf_csv(client: paramiko.SSHClient):
    """
    Handles getting user input and information about creating or appending to a
    .csv file that can be later used to rename/regroup access points.
    :param client: an authenticated SSH client
    :returns: None

    """
    path = input("Enter the path of the .csv file to be used for configuration:\n> ")
    group = ""
    while group != "exit":
        group = input(
            "Enter the group name of the set of APs you wish to add to the .csv, or type 'exit' to exit.\n> "
        )
        if group.lower() == "exit":
            break
        prompt = (
            "Would you like to interactively add AP MAC addresses now for group"
            f"{group}?\n\n"
            "   1) Enter MAC addresses interactively\n"
            "   2) Do not add MAC addresses at this time\n"
            "   3) Exit\n"
            "> "
        )
        choice = input(prompt)
        if choice.lower() == "exit" or choice == "3":
            break
        else:
            interactive_mac = choice == "1"
        create_table(group, path, client, interactive_mac)
        print("Success!\n")


def apply_conf_csv(client: paramiko.SSHClient):
    """
    Prompts for user input regarding which .csv configuration file to use,
    and then attempts to bulk rename and regroup all of the access points in the
    .csv

    The configuration .csv should have the form:

    group,name,mac
    group_of_ap,name_of_ap,mac_of_ap
    group_of_ap,name_of_ap,mac_of_ap
    ...
    group_of_ap,name_of_ap,mac_of_ap

    This function will go through each row, and attempt to rename and regroup
    the access point with the specified mac address, and set its group and name
    to the ones specified in the .csv file. If the Aruba Controller cannot find
    a connected AP with the specified MAC address, no action will be taken.
    However, if an AP with the specified MAC address is found, this AP will be
    regrouped and renamed via the Aruba Controller, which will cause the AP to
    reboot. Additionally, its row in the .csv file will be deleted, such that
    only APs that still need to be renamed will be present in the .csv file.

    This function will terminate when all APs in the .csv file are
    regrouped/renamed, or when the user signals a KeyboardInterrupt using Control-C

    :param client: an authenticated SSH client
    :returns: None

    """

    path = input("Enter the path of the .csv file to be used for configuration:\n> ")
    print("Attempting to configure access points.\nPress C-c to stop.")
    try:
        while True:
            todo = []
            done = []
            still_needed = []
            with open(path, "r", newline="") as f:
                reader = csv.DictReader(f, delimiter=",")
                for row in reader:
                    todo.append(row)
            if len(todo) < 1:
                print("Requested APs have been renamed.")
                break
            for ap in todo:
                mac = convert_mac(ap["mac"])
                if len(mac) < 10:
                    continue  # ignore blank/bad lines
                ap_name = ap["name"]
                group = ap["group"]
                # Verify AP is found:
                cmd = f"show ap database long | include {mac}"
                stdin, stdout, stderr = client.exec_command(cmd, get_pty=True)
                stdout_s = stream2str(stdout)
                if mac not in stdout_s:
                    still_needed.append(ap)
                else:
                    # Set the AP name
                    cmd = f"ap-rename wired-mac {mac} {ap_name}"
                    stdin, stdout, stderr = client.exec_command(cmd, get_pty=True)
                    print_stream(stdout)

                    # Set the AP group
                    cmd = f"ap-regroup wired-mac {mac} {group}"
                    stdin, stdout, stderr = client.exec_command(cmd, get_pty=True)
                    print_stream(stdout)

                    print(f"Sucessfully Set <{ap_name}>-<{group}>-<{mac}>")
                    done.append(ap)
            with open(path + ".swp", "w", newline="") as f:
                writer = csv.writer(f, delimiter=",")
                writer.writerow(["group", "name", "mac"])
                for ap in still_needed:
                    writer.writerow([ap["group"], ap["name"], ap["mac"]])
            os.rename(path + ".swp", path)
            if len(still_needed) > 0:
                print("\n\nCould not rename the following APs (are the APs online?):")
                pprint.pprint([x["name"] for x in still_needed])
                print("Trying again in 10s...")
                time.sleep(10)

    except KeyboardInterrupt:
        print("Stopping...\n")


if __name__ == "__main__":
    if MANAGEMENT_IP == None:
        print(
            f"No IP address set.\nPlease set Aruba Management IP in {sys.argv[0]}\n\n\tExample: MANAGEMENT_IP = '10.0.0.1'"
        )
        exit(1)
    username, password = login()

    client = setup_ssh(username, password)

    while True:
        prompt = (
            "Select an option:\n"
            "\t1) Create/Add to a configuration .csv\n"
            "\t2) Apply a configuration .csv to the Aruba Controller\n"
            "\t3) Exit the program\n"
            "> "
        )
        choice = input(prompt)
        if choice.lower() == "exit" or choice == "3":
            break
        elif choice == "1":
            write_conf_csv(client)
        elif choice == "2":
            apply_conf_csv(client)
