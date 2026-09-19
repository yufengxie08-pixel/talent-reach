from fastmcp import FastMCP


INSTRUCTIONS = (
    "Use only public or user-authorized data. Preserve source URLs and evidence. "
    "Do not infer nationality or other sensitive traits, bypass access controls, "
    "mine hidden or commit-history emails, guess corporate emails, or probe mail servers."
)


def make_server(name: str) -> FastMCP:
    return FastMCP(name, instructions=INSTRUCTIONS)

