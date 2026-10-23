package com.demo.thesis.auth;

import org.springframework.boot.context.properties.ConfigurationProperties;

import java.util.List;
import java.util.Map;

@ConfigurationProperties(prefix = "app")
public class RbacProperties {
    private Rbac rbac = new Rbac();

    public Rbac getRbac() { return rbac; }
    public void setRbac(Rbac rbac) { this.rbac = rbac; }

    public static class Rbac {
        private Map<String, List<String>> roles;
        public Map<String, List<String>> getRoles() { return roles; }
        public void setRoles(Map<String, List<String>> roles) { this.roles = roles; }
    }
}
