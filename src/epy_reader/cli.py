import argparse
import os
import shutil
import sys
import textwrap
from difflib import SequenceMatcher as SM
from typing import List, Optional, Tuple

from epy_reader import __version__
from epy_reader.lib import coerce_to_int, is_url, truncate
from epy_reader.models import LibraryItem
from epy_reader.parser import parse_html
from epy_reader.state import State
from epy_reader.utils import get_ebook_obj


def cleanup_library(state: State) -> None:
    """Cleanup non-existent file from library"""
    library_items = state.get_from_history()
    for item in library_items:
        if not os.path.isfile(item.filepath) and not is_url(item.filepath):
            state.delete_from_library(item.filepath)


def get_nth_file_from_library(state: State, n) -> Optional[LibraryItem]:
    library_items = state.get_from_history()
    try:
        return library_items[n - 1]
    except IndexError:
        return None


def get_matching_library_item(
    state: State, pattern: str, threshold: float = 0.5
) -> Optional[LibraryItem]:
    matches: List[Tuple[LibraryItem, float]] = []  # [(library_item, match_value), ...]
    library_items = state.get_from_history()
    if not library_items:
        return None

    for item in library_items:
        tomatch = f"{item.title} - {item.author}"  # item.filepath
        match_value = sum(
            [i.size for i in SM(None, tomatch.lower(), pattern.lower()).get_matching_blocks()]
        ) / float(len(pattern))
        matches.append(
            (
                item,
                match_value,
            )
        )

    sorted_matches = sorted(matches, key=lambda x: -x[1])
    first_match_item, first_match_value = sorted_matches[0]
    if first_match_item and first_match_value >= threshold:
        return first_match_item
    else:
        return None


def print_reading_history(state: State) -> None:
    termc, _ = shutil.get_terminal_size()
    library_items = state.get_from_history()
    if not library_items:
        print("No Reading History.")
        return

    print("Reading History:")
    dig = len(str(len(library_items) + 1))
    tcols = termc - dig - 2
    for n, item in enumerate(library_items):
        print(
            "{} {}".format(
                str(n + 1).rjust(dig),
                truncate(str(item), "...", tcols, tcols - 3),
            )
        )


def parse_cli_args() -> argparse.Namespace:
    prog = "epy"
    positional_arg_help_str = "[PATH | # | PATTERN | URL]"
    args_parser = argparse.ArgumentParser(
        prog=prog,
        usage=f"%(prog)s [-h] [-r] [-d] [-v] {positional_arg_help_str}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Read ebook in terminal",
        epilog=textwrap.dedent(f"""\
        examples:
          {prog} /path/to/ebook    read /path/to/ebook file
          {prog} 3                 read #3 file from reading history
          {prog} count monte       read file matching 'count monte'
                                from reading history
        """),
    )
    args_parser.add_argument("-r", "--history", action="store_true", help="print reading history")
    args_parser.add_argument("-d", "--dump", action="store_true", help="dump the content of ebook")
    args_parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=f"v{__version__}",
        help="print version and exit",
    )
    args_parser.add_argument(
        "--init",
        action="store_true",
        help="initialize epy dependencies (sdcv, chafa, dictionaries)",
    )
    args_parser.add_argument(
        "--check",
        action="store_true",
        help="check epy dependencies and report status",
    )
    args_parser.add_argument(
        "ebook",
        action="store",
        nargs="*",
        metavar=positional_arg_help_str,
        help="ebook path, history number, pattern or URL",
    )
    return args_parser.parse_args()


def find_file(args: argparse.Namespace) -> Tuple[str, bool]:
    state = State()
    cleanup_library(state)

    if args.history:
        print_reading_history(state)
        sys.exit()

    if len(args.ebook) == 0:
        last_read = state.get_last_read()
        if last_read:
            return last_read, args.dump
        else:
            sys.exit("ERROR: Found no last read ebook file.")

    elif len(args.ebook) == 1:
        nth = coerce_to_int(args.ebook[0])
        if nth is not None:
            file = get_nth_file_from_library(state, nth)
            if file:
                return file.filepath, args.dump
            else:
                print(f"ERROR: #{nth} file not found.")
                print_reading_history(state)
                sys.exit(1)
        elif is_url(args.ebook[0]):
            return args.ebook[0], args.dump
        elif os.path.isfile(args.ebook[0]):
            return args.ebook[0], args.dump

    pattern = " ".join(args.ebook)
    match = get_matching_library_item(state, pattern)
    if match:
        return match.filepath, args.dump
    else:
        sys.exit("ERROR: Found no matching ebook from history.")


def dump_ebook_content(filepath: str) -> None:
    ebook = get_ebook_obj(filepath)
    try:
        try:
            ebook.initialize()
        except Exception as e:
            sys.exit("ERROR: Badly-structured ebook.\n" + str(e))
        for i in ebook.contents:
            content = ebook.get_raw_text(i)
            src_lines = parse_html(content)
            assert isinstance(src_lines, tuple)
            # sys.stdout.reconfigure(encoding="utf-8")  # Python>=3.7
            for j in src_lines:
                sys.stdout.buffer.write((j + "\n\n").encode("utf-8"))
    finally:
        ebook.cleanup()


def _count_dicts(dict_dir: str) -> int:
    """Count how many dictionary subdirectories exist under dict_dir."""
    if not os.path.isdir(dict_dir):
        return 0
    count = 0
    for entry in os.listdir(dict_dir):
        subdir = os.path.join(dict_dir, entry)
        if os.path.isdir(subdir):
            # A stardict dictionary directory has at least one .ifo file
            if any(f.endswith(".ifo") for f in os.listdir(subdir)):
                count += 1
    return count


def check_dependencies() -> bool:
    """Check all epy dependencies and report status.

    Returns True when all checks pass, False otherwise.
    """
    # (label, ok, detail)
    checks: List[Tuple[str, bool, str]] = []

    # sdcv
    sdcv_path = shutil.which("sdcv")
    checks.append(("sdcv (dict client)", bool(sdcv_path), sdcv_path or "not installed"))

    # chafa
    chafa_path = shutil.which("chafa")
    checks.append(("chafa (terminal image)", bool(chafa_path), chafa_path or "not installed"))

    # Dictionaries
    dict_dir = os.path.expanduser("~/.stardict/dic")
    n_dicts = _count_dicts(dict_dir)
    if n_dicts:
        checks.append(("Stardict dictionaries", True, f"~/.stardict/dic/ ({n_dicts})"))
    else:
        checks.append(("Stardict dictionaries", False, "not installed"))

    # XM_* env
    for var in ("XM_KEY", "XM_MOD", "XM_URL"):
        val = os.environ.get(var)
        checks.append((var, bool(val), "set" if val else "not set"))

    # Print
    for name, ok, detail in checks:
        status = "✅" if ok else "❌"
        print(f"  {status} {name}: {detail}")

    passed = sum(1 for _, ok, _ in checks if ok)
    print(f"\nPassed: {passed}/{len(checks)}")

    return passed == len(checks)


def _install_system_deps() -> None:
    """Try to install sdcv and chafa via available system package manager.

    Only installs packages that are not already in PATH.
    """
    import subprocess

    missing = []
    if shutil.which("sdcv") is None:
        missing.append("sdcv")
    if shutil.which("chafa") is None:
        missing.append("chafa")

    if not missing:
        print("  ✅ sdcv and chafa already installed\n")
        return

    managers = [
        (["sudo", "apt-get", "install", "-y"] + missing, "apt"),
        (["sudo", "yum", "install", "-y"] + missing, "yum"),
        (["brew", "install"] + missing, "brew"),
    ]

    for cmd, name in managers:
        if shutil.which(cmd[0]) is None:
            continue
        print(f"  Trying {name} ...")
        try:
            subprocess.run(cmd, check=True)
            print(f"  ✅ {', '.join(missing)} installed via {name}\n")
            return
        except subprocess.CalledProcessError:
            print(f"  ❌ {name} failed\n")
            return
        except FileNotFoundError:
            continue

    print(f"  ⚠️  No supported package manager found. Install {' '.join(missing)} manually.\n")


def init_setup() -> None:
    """Initialize epy: install sdcv + chafa, extract dictionaries, then run check."""
    import tarfile

    # 1. Install sdcv and chafa via system package manager
    print("Installing system dependencies (sdcv, chafa) ...")
    _install_system_deps()

    # 2. Extract dictionaries
    dict_dir = os.path.expanduser("~/.stardict/dic")
    if _count_dicts(dict_dir) > 0:
        print("Dictionaries already installed at ~/.stardict/dic/, skipping.")
    else:
        data_dir = os.path.join(os.path.dirname(__file__), "data")
        dic_tar = os.path.join(data_dir, "dic.tar.gz")
        if not os.path.isfile(dic_tar):
            print(f"  ❌ Dictionary archive not found: {dic_tar}")
        else:
            print("Extracting dictionaries ...")
            os.makedirs(dict_dir, exist_ok=True)
            with tarfile.open(dic_tar, "r:gz") as tar:
                for member in tar.getmembers():
                    # Strip top-level 'dic/' prefix so we get
                    #   ~/.stardict/dic/stardict-XXX/...
                    # instead of
                    #   ~/.stardict/dic/dic/stardict-XXX/...
                    if member.name == "dic" or member.name == "dic/":
                        continue
                    if member.name.startswith("dic/"):
                        member.name = member.name[4:]
                    tar.extract(member, dict_dir)
            print("  ✅ Dictionaries extracted to ~/.stardict/dic/\n")

    # 3. Run dependency check to show remaining gaps
    print("Dependency check:")
    check_dependencies()

    # 4. Show actionable hints for remaining issues
    print()
    has_xm_missing = any(not os.environ.get(v) for v in ("XM_KEY", "XM_MOD", "XM_URL"))
    if has_xm_missing:
        print(
            "To enable smart translation (key: T), add these lines to "
            "~/.bashrc and run 'source ~/.bashrc':\n"
        )
        print('  export XM_KEY="your-api-key"')
        print('  export XM_MOD="your-model-name"')
        print('  export XM_URL="https://your-api-endpoint/v1"')
        print()
    else:
        print("All dependencies ready.")
