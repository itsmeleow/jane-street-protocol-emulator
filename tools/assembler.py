"""Two-pass assembler for the experimental PE-v0 ISA. No third-party dependencies."""
from pathlib import Path
import argparse
import re


class AssemblyError(ValueError):
    pass


REGISTERS = {"PINS": 0, "OE": 1, "X": 2, "OSR": 3, "ISR": 4, "OSR_HI": 5}
BRANCHES = {"JMP": 0, "DECJNZ": 1, "JEQ": 2, "JNE": 3}


def assemble(source: str) -> list[int]:
    labels = {}
    statements = []
    for number, raw in enumerate(source.splitlines(), 1):
        line = raw.split(";", 1)[0].strip()
        if not line:
            continue
        if ":" in line:
            label, line = line.split(":", 1)
            label = label.strip()
            if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", label):
                raise AssemblyError(f"line {number}: invalid label {label!r}")
            if label in labels:
                raise AssemblyError(f"line {number}: duplicate label {label}")
            labels[label] = len(statements)
        if line.strip():
            statements.append((number, line.strip()))
    if len(statements) > 64:
        raise AssemblyError("program exceeds 64 words")

    def integer(token, low, high):
        try:
            value = int(token, 0)
        except ValueError:
            raise AssemblyError(f"invalid integer {token!r}") from None
        if not low <= value <= high:
            raise AssemblyError(f"{token} outside {low}..{high}")
        return value

    words = []
    for number, line in statements:
        tokens = line.replace(",", " ").split()
        op, args = tokens[0].upper(), tokens[1:]
        try:
            if op in {"HALT", "PULL", "PUSH", "NOP"} and not args:
                word = {"HALT": 0, "PULL": 0x8000, "PUSH": 0x9000, "NOP": 0xB000}[op]
            elif op == "SET" and len(args) == 2:
                word = 0x1000 | (REGISTERS[args[0].upper()] << 8) | integer(args[1], 0, 255)
            elif op == "PIN" and len(args) == 3:
                bank = {"PINS": 0, "OE": 1}[args[0].upper()]
                word = 0x2000 | (bank << 4) | (integer(args[2], 0, 1) << 3) | integer(args[1], 0, 7)
            elif op in {"OUT", "OUTOD"} and len(args) == 2:
                direction = {"LSB": 0, "MSB": 1}[args[1].upper()]
                word = (0x3000 if op == "OUT" else 0xA000) | (direction << 3) | integer(args[0], 0, 7)
            elif op == "IN" and len(args) == 1:
                word = 0x4000 | integer(args[0], 0, 7)
            elif op == "WAIT" and len(args) == 2:
                word = 0x5000 | (integer(args[1], 0, 1) << 3) | integer(args[0], 0, 7)
            elif op == "DELAY" and len(args) == 1:
                word = 0x6000 | integer(args[0], 1, 4095)
            elif op in BRANCHES and len(args) == 1:
                address = labels[args[0]] if args[0] in labels else integer(args[0], 0, 63)
                if address > 63:
                    raise AssemblyError("branch target outside instruction memory")
                word = 0x7000 | (BRANCHES[op] << 8) | address
            else:
                raise AssemblyError("unknown instruction or wrong operand count")
        except (ValueError, KeyError) as error:
            raise AssemblyError(f"line {number}: {line}: {error}") from None
        words.append(word)
    if not words:
        raise AssemblyError("empty program")
    return words


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("-o", "--output", type=Path)
    args = parser.parse_args()
    try:
        words = assemble(args.source.read_text())
    except AssemblyError as error:
        parser.exit(2, f"{error}\n")
    result = "".join(f"{word:04x}\n" for word in words)
    if args.output:
        args.output.write_text(result)
    else:
        print(result, end="")


if __name__ == "__main__":
    main()
