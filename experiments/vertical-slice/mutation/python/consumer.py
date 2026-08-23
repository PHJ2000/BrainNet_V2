from contract_model import NodeView


def render(node: NodeView) -> str:
    return f"{node.order_index}:{node.content}"


if __name__ == "__main__":
    assert render(NodeView(id=1, content="root", order_index=7)) == "7:root"

