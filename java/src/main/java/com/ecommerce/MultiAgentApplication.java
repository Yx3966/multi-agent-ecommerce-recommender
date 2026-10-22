package com.ecommerce;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableAsync;

@SpringBootApplication
@EnableAsync
public class MultiAgentApplication {
    public static void main(String[] args) {
        SpringApplication.run(MultiAgentApplication.class, args);
    }
}
