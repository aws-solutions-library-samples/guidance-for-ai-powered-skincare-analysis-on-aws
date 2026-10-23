# -----------------------------------------------------------
# ECR Repository (AgentCore image only)
# -----------------------------------------------------------

resource "aws_ecr_repository" "agentcore" {
  name                 = "${local.prefix}-agentcore"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = var.enable_force_destroy

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "agentcore" {
  repository = aws_ecr_repository.agentcore.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep only last 10 images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = { type = "expire" }
    }]
  })
}
