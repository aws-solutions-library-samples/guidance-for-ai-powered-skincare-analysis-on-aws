# Shared dev environment config — committed to git.
# Local overrides go in terraform.tfvars (gitignored).

# Custom domain (optional) — leave empty to use default CloudFront domain
custom_domain       = ""
acm_certificate_arn = ""
route53_zone_id     = ""

# Dev settings
enable_force_destroy = true
