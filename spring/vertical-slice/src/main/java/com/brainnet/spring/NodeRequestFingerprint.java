package com.brainnet.spring;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.HexFormat;

/** The same UTF-8, length-prefixed node-create-v1 format as FastAPI. */
final class NodeRequestFingerprint {
    private NodeRequestFingerprint() {}

    static String hash(ApiModels.NodeCreate body) {
        String[] values = {
            body.content(), body.ai_prompt(),
            body.parent_id() == null || body.parent_id() == 0 ? null : body.parent_id().toString(),
            body.depth() == null ? "0" : body.depth().toString(),
            body.order() == null ? "0" : body.order().toString(),
            position(body.pos_x()), position(body.pos_y()), body.state()
        };
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            digest.update("node-create-v1\n".getBytes(StandardCharsets.UTF_8));
            for (String value : values) {
                byte[] bytes = value == null ? null : value.getBytes(StandardCharsets.UTF_8);
                digest.update((bytes == null ? "-1:" : bytes.length + ":").getBytes(StandardCharsets.UTF_8));
                if (bytes != null) digest.update(bytes);
            }
            return HexFormat.of().formatHex(digest.digest());
        } catch (java.security.NoSuchAlgorithmException ex) {
            throw new IllegalStateException(ex);
        }
    }

    private static String position(Double value) {
        return HexFormat.of().toHexDigits(Double.doubleToLongBits(value == null || value == 0 ? 0.0 : value));
    }
}
