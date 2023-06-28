# Full streaming support

Towards better supporting all streaming flavors via caikit

## Current API

```python
@caikit.task(required_params={"tokens": Iterable[str]}, output_type=Iterable[TokenClassification])
class StreamingTokenClassification(caikit.core.TaskBase):
  pass

@caikit.task(required_params={"text": str}, output_type=Iterable[TokenClassification])
class OutputStreamingTokenClassification(caikit.core.TaskBase):
  pass

@caikit.task(required_params={"text": str}, output_type=TokenClassifications)
class TokenClassification(caikit.core.TaskBase):
  pass


@caikit.module(id=..., task=StreamingTokenClassification)
class MyBiDiTokenClassifier(caikit.core.ModuleBase):
  def run(self, tokens: DataStream[str], threshold: float) -> DataStream[TokenClassification]:
    ...

@caikit.module(id=..., task=OutputStreamingTokenClassification)
class MyOutputStreamingTokenClassifier(caikit.core.ModuleBase):
  def run(self, text: str, threshold: float) -> DataStream[TokenClassification]:
    ...
  
@caikit.module(id=..., task=TokenClassification)
class MyTokenClassifier(caikit.core.ModuleBase):
  def run(self, text: str, threshold: float) -> TokenClassifications:
    ...
```

Problems:
- No coupling between tasks that are logically the same
- Multiple tasks and modules required
- Multiple concrete models must be loaded to support different streaming flavors


## Proposed API

```python
@caikit.task()
class TokenClassification:
  unary_params: {"text": str}
  streaming_params: {"text": Iterable[str]}
  unary_output_type: TokenClassifications
  streaming_output_type: Iterable[TokenClassification]

@caikit.module(id="foobar", task=TokenClassification)
class MyTokenClassifierModule(caikit.ModuleBase):
  
    @TokenClassification.taskmethod(stream_flavor=UNARY_UNARY)
    def run(self, text: str) -> TokenClassifications:
      ...
    
    @TokenClassification.taskmethod(stream_flavor=STREAM_STREAM)
    def run_bidi_stream(self):
      ...
    
    @TokenClassification.taskmethod(stream_flavor=STREAM_UNARY)
    def run_stream_in(self):
      ...
    
    @TokenClassification.taskmethod(stream_flavor=UNARY_STREAM)
    def run_stream_out(self):
      ...
```

- More detailed task api includes unary and streaming types for a single logical task
- Explicit method mappings allow a single module to define unary and streaming behavior
- one task, one module --> one single model id can be loaded and invoked in unary or streaming fashion
- Can still be fully backwards-compatible
