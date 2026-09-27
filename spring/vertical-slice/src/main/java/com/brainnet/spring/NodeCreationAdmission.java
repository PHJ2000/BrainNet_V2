package com.brainnet.spring;

import java.util.concurrent.Semaphore;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;

/** Bound provider/DB work before borrowing connections or claiming idempotency keys. */
@Component
class NodeCreationAdmission {
    private final Limit regular;
    private final Limit ai;

    NodeCreationAdmission(
            @Value("${NODE_CREATE_CONCURRENCY:32}") int regularCapacity,
            @Value("${NODE_CREATE_MAX_WAITING:512}") int regularWaiting,
            @Value("${NODE_CREATE_WAIT_SECONDS:5}") double regularSeconds,
            @Value("${NODE_AI_CREATE_CONCURRENCY:32}") int aiCapacity,
            @Value("${NODE_AI_CREATE_MAX_WAITING:512}") int aiWaiting,
            @Value("${NODE_AI_CREATE_WAIT_SECONDS:5}") double aiSeconds) {
        regular = new Limit(regularCapacity, regularWaiting, regularSeconds);
        ai = new Limit(aiCapacity, aiWaiting, aiSeconds);
    }

    Permit enter(boolean isAi) { return (isAi ? ai : regular).enter(); }

    static final class Limit {
        private final Semaphore slots;
        private final AtomicInteger waiting = new AtomicInteger();
        private final int maxWaiting;
        private final long waitNanos;

        Limit(int capacity, int maxWaiting, double seconds) {
            if (capacity < 1 || maxWaiting < 0 || !Double.isFinite(seconds) || seconds <= 0) {
                throw new IllegalArgumentException("Invalid node creation admission limits");
            }
            slots = new Semaphore(capacity);
            this.maxWaiting = maxWaiting;
            waitNanos = Math.max(1, (long) (seconds * 1_000_000_000));
        }

        Permit enter() {
            if (slots.tryAcquire()) return slots::release;
            int queued = waiting.incrementAndGet();
            try {
                if (queued > maxWaiting || !slots.tryAcquire(waitNanos, TimeUnit.NANOSECONDS)) throw busy();
                return slots::release;
            } catch (InterruptedException ex) {
                Thread.currentThread().interrupt();
                throw busy();
            } finally {
                waiting.decrementAndGet();
            }
        }

        private ApiExceptionHandler.ApiException busy() {
            return new ApiExceptionHandler.ApiException(HttpStatus.SERVICE_UNAVAILABLE, "NODE_CREATION_BUSY",
                    "Node creation is busy; retry with the same Idempotency-Key");
        }
    }

    interface Permit extends AutoCloseable { @Override void close(); }
}
