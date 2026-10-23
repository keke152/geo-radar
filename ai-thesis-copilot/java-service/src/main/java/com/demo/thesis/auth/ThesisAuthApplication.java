package com.demo.thesis.auth;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.EnableConfigurationProperties;

@SpringBootApplication
@EnableConfigurationProperties(RbacProperties.class)
public class ThesisAuthApplication {
    public static void main(String[] args) {
        SpringApplication.run(ThesisAuthApplication.class, args);
    }
}
