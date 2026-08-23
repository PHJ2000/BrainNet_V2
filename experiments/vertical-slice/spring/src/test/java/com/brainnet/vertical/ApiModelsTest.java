package com.brainnet.vertical;

import static org.assertj.core.api.Assertions.assertThat;
import org.junit.jupiter.api.Test;

class ApiModelsTest {
    @Test void nodeViewContractExposesOrderIndex() {
        var view = new ApiModels.NodeView(1, 1, 1L, "x", "ACTIVE", 0.0, 0.0, 0, 7, null, 0);
        assertThat(view.order_index()).isEqualTo(7);
    }
}

