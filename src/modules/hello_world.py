from src.modules.base import BaseModule

class HelloWorldModule(BaseModule):
    """A dummy module to verify the module system."""
    name = "hello_world"
    description = "Test module for the module system verification."
    priority = 0  # Run first

    def run(self) -> bool:
        self.logger.info("Hello World from the feature module system!")
        self.logger.info(f"Context work dir: {self.ctx.work_dir}")
        self.logger.info(f"Target device: {self.ctx.target_device_code}")
        return True
