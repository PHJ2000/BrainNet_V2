import pytest
from pydantic import ValidationError

from app.models.node import NodeCreate, NodeUpdate
from app.models.project import ProjectCreate, ProjectUpdate
from app.models.tag import TagCreate, TagUpdate


@pytest.mark.parametrize("model,values", [
    (ProjectCreate, {"name": ""}),
    (ProjectUpdate, {"name": ""}),
    (ProjectCreate, {"name": "x" * 121}),
    (NodeCreate, {"content": "node", "order": -1}),
    (NodeUpdate, {"order": 2147483648}),
    (NodeUpdate, {"pos_x": float("inf")}),
    (NodeCreate, {"content": "bad\x00text"}),
    (NodeUpdate, {"content": "\ud800"}),
    (TagCreate, {"name": "x" * 81}),
    (TagUpdate, {"color": "x" * 8}),
])
def test_ordinary_writes_reject_values_that_cannot_be_stored_or_backed_up(model, values):
    with pytest.raises(ValidationError):
        model(**values)
