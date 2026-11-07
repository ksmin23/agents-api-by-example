"""Training-only stdio MCP server; logs go to stderr via the MCP SDK."""
import argparse
import json
from pathlib import Path
import re

from mcp.server.fastmcp import FastMCP

server=FastMCP("sales-targets")
TARGETS=None


@server.tool()
def get_sales_target(period: str) -> dict:
    """Return the fictional monthly revenue target for YYYY-MM."""
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])",period):
        raise ValueError("invalid_period")
    values=json.loads(TARGETS.read_text())
    if period not in values:
        raise ValueError("unknown_period")
    return {"period":period,**values[period]}


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--data',type=Path,required=True)
    args=parser.parse_args()
    TARGETS=args.data.resolve(strict=True)
    server.run(transport='stdio')
