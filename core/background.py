import functools
import json

def background_task(func):
    """
    Decorator to queue a function for background execution.
    The function arguments must be JSON serializable.
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        from core.models import BackgroundJob
        
        # Ensure arguments are JSON serializable
        try:
            json.dumps(args)
            json.dumps(kwargs)
        except TypeError as e:
            raise ValueError(f"Arguments must be JSON serializable: {e}")
            
        job = BackgroundJob.objects.create(
            task_name=f"{func.__module__}.{func.__name__}",
            args=args,
            kwargs=kwargs
        )
        return job

    # Attach the original function so the worker can execute it directly
    wrapper.execute = func
    return wrapper
