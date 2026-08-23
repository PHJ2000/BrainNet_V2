from pydantic import BaseModel


class NodeView(BaseModel):
    id: int
    content: str
    order_index: int
