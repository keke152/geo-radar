package com.demo.thesis.auth;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api")
public class AccessController {
    private final AccessService accessService;

    public AccessController(AccessService accessService) {
        this.accessService = accessService;
    }

    @PostMapping("/auth/authorize")
    public Map<String, Object> authorize(@Valid @RequestBody AccessRequest request) {
        boolean allowed = accessService.authorize(request.userId(), request.role(), request.scope());
        if (!allowed) throw new ResponseStatusException(HttpStatus.FORBIDDEN, "role does not allow requested scope");
        return Map.of("allowed", true, "user_id", request.userId(), "role", request.role(), "scope", request.scope());
    }

    @GetMapping("/users")
    public List<Map<String, String>> users() {
        return accessService.demoUsers();
    }

    @GetMapping("/audit")
    public List<String> audit() {
        return accessService.readAudit();
    }

    @PostMapping("/rate-limit/check")
    public Map<String, Object> rateLimit(@RequestParam @NotBlank String key) {
        return Map.of("allowed", accessService.allowRequest(key), "limit_per_minute", accessService.limitPerMinute());
    }

    public record AccessRequest(@NotBlank String userId, @NotBlank String role, @NotBlank String scope) {}
}
