# -----------------------------------------------------------
# Bedrock Guardrails — Content filtering, PII redaction, topic blocking
# Required for demo security review (Q16)
# -----------------------------------------------------------

resource "aws_bedrock_guardrail" "smart_beauty" {
  name        = "${local.prefix}-guardrail"
  description = "Content filtering and PII protection for Smart Beauty demo"

  # Block harmful content categories
  content_policy_config {
    filters_config {
      # Sexual content
      input_strength  = "HIGH"
      output_strength = "HIGH"
      type            = "SEXUAL"
    }

    filters_config {
      # Violence and gore
      input_strength  = "HIGH"
      output_strength = "HIGH"
      type            = "VIOLENCE"
    }

    filters_config {
      # Hate speech
      input_strength  = "HIGH"
      output_strength = "HIGH"
      type            = "HATE"
    }

    filters_config {
      # Insults and profanity
      input_strength  = "MEDIUM"
      output_strength = "MEDIUM"
      type            = "INSULTS"
    }

    filters_config {
      # Misconduct (illegal activities)
      input_strength  = "HIGH"
      output_strength = "HIGH"
      type            = "MISCONDUCT"
    }

    filters_config {
      # Prompt attacks (jailbreaks)
      input_strength  = "HIGH"
      output_strength = "NONE"
      type            = "PROMPT_ATTACK"
    }
  }

  # Block configured PII. Age is intentionally allowed for skin-age estimates.
  sensitive_information_policy_config {
    pii_entities_config {
      action = "BLOCK"
      type   = "EMAIL"
    }

    pii_entities_config {
      action = "BLOCK"
      type   = "PHONE"
    }

    pii_entities_config {
      action = "BLOCK"
      type   = "NAME"
    }

    pii_entities_config {
      action = "BLOCK"
      type   = "ADDRESS"
    }

    pii_entities_config {
      action = "BLOCK"
      type   = "CREDIT_DEBIT_CARD_NUMBER"
    }

    pii_entities_config {
      action = "BLOCK"
      type   = "US_SOCIAL_SECURITY_NUMBER"
    }

    pii_entities_config {
      action = "BLOCK"
      type   = "IP_ADDRESS"
    }
  }

  # Block specific topics (narrow scope to avoid blocking core functionality)
  topic_policy_config {
    topics_config {
      name       = "medical-diagnosis"
      definition = "Medical diagnosis of diseases, prescription of medications, or treatment of medical conditions. Does NOT include skincare product recommendations or skin type analysis."
      examples = [
        "Do I have skin cancer?",
        "What prescription medication should I take?",
        "Can you diagnose this rash as eczema or psoriasis?",
        "Should I see a dermatologist for this medical condition?"
      ]
      type = "DENY"
    }

    topics_config {
      name       = "financial-advice"
      definition = "Investment advice, financial planning, stock recommendations, or monetary investment guidance"
      examples = [
        "Should I invest in this skincare company stock?",
        "What's the best investment strategy for beauty products?",
        "How should I allocate my portfolio?"
      ]
      type = "DENY"
    }

    topics_config {
      name       = "legal-advice"
      definition = "Legal guidance, lawsuit recommendations, regulatory compliance advice, or legal interpretations"
      examples = [
        "Can I sue this company for skin damage?",
        "What are my legal rights regarding product liability?",
        "Should I file a lawsuit?"
      ]
      type = "DENY"
    }
  }

  # Block messages that violate guardrails
  blocked_input_messaging   = "I cannot process this request as it contains inappropriate content or sensitive information. Please rephrase your question about skincare products."
  blocked_outputs_messaging = "I cannot provide this response as it may contain inappropriate content. Please ask a different question about skincare recommendations."

  tags = {
    Name        = "${local.prefix}-guardrail"
    Environment = var.environment
    Purpose     = "demo-security"
  }
}

# Create a version of the guardrail (required for use)
resource "aws_bedrock_guardrail_version" "smart_beauty" {
  guardrail_arn = aws_bedrock_guardrail.smart_beauty.guardrail_arn
  description   = "Production version for ${var.environment}"
  skip_destroy  = true

  lifecycle {
    create_before_destroy = true
    replace_triggered_by  = [aws_bedrock_guardrail.smart_beauty]
  }
}

# Output guardrail details for AgentCore configuration
output "guardrail_id" {
  description = "Bedrock Guardrail ID"
  value       = aws_bedrock_guardrail.smart_beauty.guardrail_id
}

output "guardrail_arn" {
  description = "Bedrock Guardrail ARN"
  value       = aws_bedrock_guardrail.smart_beauty.guardrail_arn
}

output "guardrail_version" {
  description = "Bedrock Guardrail Version"
  value       = aws_bedrock_guardrail_version.smart_beauty.version
}
