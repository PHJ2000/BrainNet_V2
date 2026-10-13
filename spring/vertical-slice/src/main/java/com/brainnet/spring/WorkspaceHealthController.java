package com.brainnet.spring;

import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.*;

import java.util.*;

@RestController
class WorkspaceHealthController {
    final NodeOutboxService outbox;
    final WorkspaceProposalService proposals;

    WorkspaceHealthController(NodeOutboxService outbox, WorkspaceProposalService proposals) {
        this.outbox = outbox;
        this.proposals = proposals;
    }

    @GetMapping("/health/events")
    WorkspaceViews.EventHealth events() {
        return new WorkspaceViews.EventHealth("spring", outbox.pendingCount());
    }

    @GetMapping(value = "/metrics", produces = MediaType.TEXT_PLAIN_VALUE)
    String metrics() {
        return "brainnet_outbox_pending "
                + outbox.pendingCount()
                + "\nbrainnet_ai_worker_ready "
                + (proposals.health().ready() ? 1 : 0)
                + "\nbrainnet_ai_worker_failures_total "
                + proposals.health().failures()
                + "\n";
    }
}
