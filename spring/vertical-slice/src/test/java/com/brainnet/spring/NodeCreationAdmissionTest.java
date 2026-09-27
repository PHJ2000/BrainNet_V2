package com.brainnet.spring;

import static org.assertj.core.api.Assertions.*;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;

class NodeCreationAdmissionTest {
    @Test
    void regularAndAiHaveIndependentCapacityAndReleaseAfterFailure() {
        var admission = new NodeCreationAdmission(1, 0, 1, 1, 0, 1);
        try (var regular = admission.enter(false); var ai = admission.enter(true)) {
            assertThatThrownBy(() -> admission.enter(false)).isInstanceOf(ApiExceptionHandler.ApiException.class);
            assertThatThrownBy(() -> admission.enter(true)).isInstanceOf(ApiExceptionHandler.ApiException.class);
        }
        try (var regular = admission.enter(false); var ai = admission.enter(true)) {
            assertThat(regular).isNotNull();
            assertThat(ai).isNotNull();
        }
    }

    @Test
    void waitingTimesOutAndReturnsRetryContractWithoutLeakingCapacity() {
        var limit = new NodeCreationAdmission.Limit(1, 1, 0.01);
        try (var held = limit.enter()) {
            var exception = catchThrowableOfType(ApiExceptionHandler.ApiException.class, limit::enter);
            assertThat(exception.code).isEqualTo("NODE_CREATION_BUSY");
            var response = new ApiExceptionHandler().api(exception, new MockHttpServletRequest());
            assertThat(response.getStatusCode().value()).isEqualTo(503);
            assertThat(response.getHeaders().getFirst("Retry-After")).isEqualTo("1");
        }
        try (var recovered = limit.enter()) { assertThat(recovered).isNotNull(); }
    }

    @Test
    void invalidLimitsFailAtStartup() {
        assertThatIllegalArgumentException().isThrownBy(() -> new NodeCreationAdmission.Limit(0, 1, 1));
        assertThatIllegalArgumentException().isThrownBy(() -> new NodeCreationAdmission.Limit(1, -1, 1));
        assertThatIllegalArgumentException().isThrownBy(() -> new NodeCreationAdmission.Limit(1, 1, Double.NaN));
    }
}
