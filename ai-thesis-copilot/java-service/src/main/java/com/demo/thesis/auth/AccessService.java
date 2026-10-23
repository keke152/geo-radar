package com.demo.thesis.auth;

import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.stereotype.Service;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.UUID;

@Service
public class AccessService {
    private static final Map<String, List<String>> DEMO_USERS = Map.of(
            "demo-researcher", List.of("researcher"),
            "demo-advisor", List.of("advisor"),
            "demo-admin", List.of("admin"));
    private final StringRedisTemplate redis;
    private final Map<String, List<String>> roles;
    private final Map<String, Deque<Long>> fallbackWindows = new ConcurrentHashMap<>();
    private final Path auditFile;
    private final int rpm;

    public AccessService(StringRedisTemplate redis, RbacProperties properties,
                         org.springframework.core.env.Environment environment) {
        this.redis = redis;
        this.roles = properties.getRbac().getRoles();
        this.auditFile = Path.of(environment.getProperty("app.audit.file", "./data/audit.log"));
        this.rpm = environment.getProperty("app.rate-limit.requests-per-minute", Integer.class, 30);
    }

    public boolean authorize(String userId, String role, String scope) {
        boolean identityHasRole = DEMO_USERS.getOrDefault(userId, List.of()).contains(role);
        List<String> allowedScopes = roles.getOrDefault(role, List.of());
        boolean permitted = identityHasRole && (allowedScopes.contains("*") || allowedScopes.contains(scope));
        audit(String.format("%s user=%s role=%s scope=%s result=%s", Instant.now(), userId, role, scope, permitted ? "allow" : "deny"));
        return permitted;
    }

    public boolean allowRequest(String key) {
        String redisKey = "thesis:rate:" + key;
        try {
            DefaultRedisScript<Long> script = new DefaultRedisScript<>(
                    "local t=redis.call('TIME'); local now=t[1]*1000+math.floor(t[2]/1000); " +
                    "redis.call('ZREMRANGEBYSCORE',KEYS[1],0,now-60000); " +
                    "redis.call('ZADD',KEYS[1],now,now..'-'..ARGV[1]); " +
                    "redis.call('EXPIRE',KEYS[1],61); return redis.call('ZCARD',KEYS[1])", Long.class);
            Long count = redis.execute(script, List.of(redisKey), UUID.randomUUID().toString());
            return count != null && count <= rpm;
        } catch (Exception unavailable) {
            long now = System.currentTimeMillis();
            Deque<Long> hits = fallbackWindows.computeIfAbsent(key, ignored -> new ArrayDeque<>());
            synchronized (hits) {
                while (!hits.isEmpty() && hits.peekFirst() < now - 60_000) hits.removeFirst();
                if (hits.size() >= rpm) return false;
                hits.addLast(now);
                return true;
            }
        }
    }

    public int limitPerMinute() { return rpm; }

    public List<Map<String, String>> demoUsers() {
        return DEMO_USERS.entrySet().stream().map(e -> Map.of("user_id", e.getKey(), "role", e.getValue().get(0))).toList();
    }

    private void audit(String line) {
        try {
            Files.createDirectories(auditFile.getParent());
            Files.writeString(auditFile, line + System.lineSeparator(), java.nio.file.StandardOpenOption.CREATE, java.nio.file.StandardOpenOption.APPEND);
        } catch (IOException ignored) { /* demo audit fallback is deliberately non-blocking */ }
    }

    public List<String> readAudit() {
        try {
            if (!Files.exists(auditFile)) return List.of();
            List<String> lines = Files.readAllLines(auditFile);
            return lines.subList(Math.max(0, lines.size() - 100), lines.size());
        } catch (IOException e) { return List.of("audit log unavailable"); }
    }
}
