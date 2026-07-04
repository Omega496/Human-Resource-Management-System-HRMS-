import os
import abc

class SecretsProvider(abc.ABC):
    @abc.abstractmethod
    def get(self, name: str) -> str:
        """Retrieves a secret by name."""
        pass

class EnvSecretsProvider(SecretsProvider):
    def get(self, name: str) -> str:
        # In production, this must be swapped for a real secrets-manager client
        # e.g., HashiCorp Vault, AWS Secrets Manager, Google Cloud Secret Manager.
        if name == "pseudonymization_pepper":
            pepper = os.environ.get("PSEUDONYMIZATION_PEPPER")
            if not pepper:
                # Local dev fallback for testing safety
                return "local_dev_secret_pepper_value_32_bytes_long"
            return pepper
        raise KeyError(f"Secret {name} not found")

secrets_provider = EnvSecretsProvider()
