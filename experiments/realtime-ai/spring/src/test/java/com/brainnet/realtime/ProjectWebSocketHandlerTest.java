package com.brainnet.realtime;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class ProjectWebSocketHandlerTest {
    @Test
    void startsWithNoConnections() {
        assertThat(new ProjectWebSocketHandler().connectionCount()).isZero();
    }
}
