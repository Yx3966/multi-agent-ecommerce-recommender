package com.ecommerce.config;

import org.springframework.ai.chat.client.ChatClient;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class LLMConfig {

    @Bean
    public ChatClient.Builder chatClientBuilder(ChatClient.Builder builder) {
        return builder;
    }
}
