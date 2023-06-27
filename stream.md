# streeeeeeams


## 4 modes of operation

unary
```python
def run(input: InputType, other_param: float) -> OutputType
```

output streaming
```python
def run(input: InputType, other_param: float) -> Iterable[OutputType]
```

input streaming
```python
def run(input: Iterable[InputType], other_param: float) -> OutputType
```

bidirectional streaming
```python
def run(input: Iterable[InputType], other_param: float) -> Iterable[OutputType]
```

## types?

I/O types _could_ be the same in streaming vs unary cases: e.g. `text generation` could output a raw `str` in unary mode, 
and output a `DataStream[str]` in streaming mode.

But they could also be different, e.g. for TokenClassification output:
```python
class TokenClassifications:
    results: List[TokenClassification]
    maybe_other_stuff: SomeType

class TokenClassification:
    start: int
    end: int
    entity: ...


# unary:
def run(...) -> TokenClassifications:
# output streaming
def run(...) -> DataStream[TokenClassification]:
```

```python
# unary text gen:
def run(prompt: str) -> GeneratedText:
# output streaming
def run(prompt: str) -> DataStream[GeneratedToken]:

@dataobject:
class GeneratedText:
  text: str
  tokens: List[GeneratedSpan]
  
@dataobject
class GeneratedSpan:
    token: str
    start: int
    end: int
    generation_code: Reason
    
enum Reason:
    STOPPED = 1
    MAX_TOKENS = 2
    ...
```


Whether or not the type is the same, translation is still required.
e.g. split a string into tokens to get a stream of streams, or stream over the `.results` attribute on an output data model

## optional (/other?) parameters

Assume for a hot sec that there's a single "main" input and output type for a task...
Both the input and output can also have other "optional" parameters/fields

this causes some issues with streaming, usually the fields for the "other things" are in the streaming message type,
and they are usually set on the first item of the stream and left unset on subsequent messages.

## Can a module implement both a unary and stream-flavored run?

?????

If yes: only one flavor or all of them? How to differentiate?
```python
class MyModule:

    def run(self, input: InputType) -> OutputType:
        pass

    def run_stream(self, input: InputType) -> DataStream[SubOutputType]:
        pass

    # uh-oh, same name for different stream flavor
    def run_stream(self, input: DataStream[SubInputType]) -> OutputType:
        pass

    # degenerate: provide type unions for streams
    def run(self, input: InputType | DataStream[SubInputType], streaming_mode: Enum) -> OutputType | DataStream[SubOutputType]:
        # streaming_mode could be kwargs-only like `kwargs["streaming_mode"]
        if streaming_mode == UNARY_UNARY:
            error.type_check(InputType, input)
        # Lot of effort, boilerplate code for implementer...
        ...
```
- Could have `unary_unary`, `unary_stream`, `stream_stream`, `stream_unary` methods on modules, alias `run` to `unary_unary`
- Allowing only a single streaming flavor per task is probably _not_ sufficient, e.g. an entities (token classification) task should be able to run in at least:
  - bidi streaming mode: stream text in and stream entities out as they're detected (as a post-processor on a generative LLM that is streaming out tokens)
  - output streaming mode: text in, stream entities out (as an LLM implementation of entity detection that will generate the entities results in a stream)
- ergo -> if we have one `run_stream` then concrete modules of the same task may implement it differently


If no: Then modules of the same logical task would have different python `.run` APIs
- If used via the runtime, the server can translate to the other flavors of streaming
- If used via python, a user may want "just unary" and be disappointed that `.run` needs a stream / outputs a stream :(


Noodling: Can `caikit.core` be responsible for default implementations of `unary_unary`, `unary_stream`, `stream_stream`, `stream_unary` that try to translate based on:
- Task-level information about how that translation should be done
- Finding an actual concrete implementation of those


------------
### Noodle 1: Can we define the flavors of streams in one task?
```python
@task(required_param=("text"))
class TokenClassification:
  # param_name: "text" # this is a value... would need to be in decorator ^^
  unary_input_type: str
  streaming_input_type: str
  unary_output_type: TokenClassifications
  streaming_output_type: TokenClassification
```

could translate to a runtime with:

```protobuf
message TokenClassificationRequest {
  text string = 1;
}

service NLPService {
  rpc TokenClassification(TokenClassificationRequest) returns (TokenClassifications);
  
  rpc TokenClassificationStream(TokenClassificationRequest) returns (stream TokenClassification)
  
  rpc TokenClassificationStreamUnary(stream TokenClassificationRequest) returns (TokenClassifications);
  
  rpc TokenClassificationStreamStream(stream TokenClassificationRequest) returns (stream TokenClassification);
}
```

Yes, but?

Still has the same api problems, where you now have a bunch of `TokenClassification` endpoints and you need to either:
- call the correct one for a given model or
- make sure your model supports all of them


### Noodle 2: Can we translate to/from unary -> streaming?

```python
@task(required_param=("text"))
class TokenClassification:
  # param_name: "text" # this is a value... would need to be in decorator ^^
  unary_input_type: str
  streaming_input_type: str
  unary_output_type: TokenClassifications
  streaming_output_type: TokenClassification
  
  def unary_to_stream_output(output: T) -> Iterable[V]:
    for token_classification in output.results:
      yield token_classification
  
  def stream_to_unary_output(output_stream: Iterable[T]) -> V:
    return TokenClassifications(results=list(output_stream))
  
  def stream_to_unary_input(input_stream: Iterable[T]) -> V:
    # hmm...
    text = " ".join(input_stream)
    return text
    
  def unary_to_stream_input(input: T) -> Iterable[V]:
    # HMMMMMMMMMMM
    return input.split(" ")


class ModuleBase:

    ...
    
    def unary_unary(self, *args, **kwargs):
      if method_overridden(self.run):
        return self.run(*args, **kwargs)
      if method_overridden(self.unary_stream):
        # Only works if there's a task
        return self.TASK.stream_to_unary_output(self.unary_stream(*args, **kwargs))
      if method_overridden(self.stream_stream):
        # Need to find the "one true input param"
        if self.TASK.param_name in kwargs:
          kwargs[self.TASK.param_name] = self.TASK.unary_to_stream_input(kwargs[self.TASK.param_name])
        else:
          args[0] = self.TASK.unary_to_stream_input(args[0])
        return self.TASK.stream_to_unary_output(self.stream_stream(*args, **kwargs))
      #... etc.

    # ... etc.
```

Problems:
- translating from a document (unary) to tokens (strings) requires a tokenizer. The inverse requires a detokenizer.
- the param name is a value and still needs to be in the decorator
- this assumes single input and would be hard to extend
- translation only works with tasked modules
- extremely gorpy logic to do the unary <---> streaming auto-translation (maybe this is a _good_ thing?)

```python
import caikit.core


@task(required_param=("text"))
class TokenClassification:
  # param_name: "text" # this is a value... would need to be in decorator ^^
  unary_input_type: str
  streaming_input_type: str
  unary_output_type: TokenClassifications
  streaming_output_type: TokenClassification


...


class TokenClassificationBase(caikit.core.ModuleBase):
  
  def __init__(self, tokenizer: Tokenizer, detokenizer: Detokenizer):
    self.tokenizer = tokenizer
    self.detokenizer = detokenizer
    
  def unary_to_stream_output(self, output: T) -> Iterable[V]:
    for token_classification in output.results:
      yield token_classification

  def stream_to_unary_output(self, output_stream: Iterable[T]) -> V:
    return TokenClassifications(results=list(output_stream))
  
  def stream_to_unary_input(self, input_stream: Iterable[T]) -> V:
    return self.detokenizer.detokenize(input_stream)
    
  def unary_to_stream_input(self, input: T) -> Iterable[V]:
    return self.tokenizer.tokenize(input)
```

Problems:
- How is this any better than requiring the module to implement all of its own `unary_unary`, `unary_stream`... etc




--------------------------

## What can we do _right now_?


### Option 1: Continue on the same path

```python
import caikit.core


@caikit.task(required_params={"tokens": Iterable[str]}, output_type=Iterable[TokenClassification])
class StreamingTokenClassification(caikit.core.TaskBase):
  pass

@caikit.task(required_params={"text": str}, output_type=TokenClassifications)
class TokenClassification(caikit.core.TaskBase):
  pass


@caikit.module(id=..., task=StreamingTokenClassification)
class MyBiDiTokenClassifier(caikit.core.ModuleBase):
  def run(self, tokens: DataStream[str], threshold: float) -> DataStream[TokenClassification]:
    ...

@caikit.module(id=..., task=TokenClassification)
class MyTokenClassifier(caikit.core.ModuleBase):
  def run(self, text: str, threshold: float) -> TokenClassifications:
    ...
```

Pros:
- Get out the door
- Minimal changes to caikit at all

Cons:
- User (Application developer OR end user) has to figure out that this particular model is the one they need to call for this particular endpoint
  - A model id that works for TokenClassification _will not_ work for StreamingTokenClassification
- User (Caikit content author) needs to write multiple modules for multiple streaming flavors
- User (Application developer OR Application Operator) needs to manage the deployment of separate models for separate streaming flavors

Migration?:
(Assume we want either multi-task modules _or_ logical tasks with unary+streaming support)
- Now we have models (on disk artifacts) sitting around with modules ids that would be going away
  - Tactical migration? Alias both / all modules to the one multi-task model?
```python
@caikit.module(id=old_streaming_id, task=NewMultiTask)(NewMultiTaskModule)
```
- This would probably break python APIs though, loading an old streaming model id would (probably) yield a module with two separate methods instead of one `.run` that has streaming


### Option 2: Quickly implement multi-task modules

```python
import caikit.core


@caikit.task(required_params={"tokens": Iterable[str]}, output_type=Iterable[TokenClassification])
class StreamingTokenClassification(caikit.core.TaskBase):
  pass

@caikit.task(required_params={"text": str}, output_type=TokenClassifications)
class TokenClassification(caikit.core.TaskBase):
  pass


@caikit.module(id=..., task={StreamingTokenClassification: "run_bidi_stream", TokenClassification: "run"})
class MyTokenClassifier(caikit.core.ModuleBase):
  def run_bidi_stream(self, tokens: DataStream[str], threshold: float) -> DataStream[TokenClassification]:
    ...
  
  def run(self, text: str, threshold: float) -> TokenClassifications:
    ...

```

Pros:
- Single module implements both unary and streaming
- Single concrete model ID can be used for multiple endpoints for a task
- Extremely explicit which tasks (streaming flavors) a module _does_ implement
- Allows authors the flexibility to name run methods whatever the hell they want
- Probably less migration headache later for both
  - Module authors, who don't need to combine modules later and
  - Application operators, who don't need to deal with managing a migration from multiple to single models

Cons:
- Does not guarantee that a single concrete model id will work for all flavored endpoints for a logical task
- Doesn't standardize on names for different streaming flavors of run methods
- Breaks python api contract that you can swap task models out and call `.run`
  - Can we fix this by dynamically redirecting `model.run` based on the inputs...?
  - Not quite because
    - Multiple tasks probably all have the same input params (NLP tasks all take text)
    - w/ unary input, can't determine if unary or streaming output is required
  - Maybe a `${TASK}.load(model_path)` can load a multi-task model and register a run method redirect...
  - See Noodle 3
- Requires extra runtime changes to implement


### Option 3: Quickly implement streaming flavors on tasks

```python

@task(required_param=("text"))
class TokenClassification:
  # param_name: "text" # this is a value... would need to be in decorator ^^
  unary_input_types={"text": str, "stuff": int}
  streaming_input_type: str
  unary_output_type: TokenClassifications
  streaming_output_type: TokenClassification

@caikit.module(id="foobar", task=TokenClassification)
class MyTokenClassifierModule(caikit.ModuleBase):
  
    @TokenClassification.taskmethod()
    @taskmethod(TokenClassification, streaminess_flavor=UNARY_UNARY)
    def run(self, text: str) -> TokenClassifications:
      ...
    
    def run_bidi_stream(self):
      ...
    
    def run_stream_in(self):
      ...
    
    def run_stream_out(self):
      ...

    def run_batch(self, texts: List[str]) -> List[TokenClassifications]:
      
    @taskmethod(TokenClassification, streaminess_flavor=UNARY_UNARY, batched=True)
    def run_batch_stream(self, texts: List[str]) -> List[DataStream[TokenClassification]]:
        # default impl calls run
```

Pros:
- single module implements streaming flavors
- single concrete model ID can be used for multiple endpoints for a task
- enforces the python names for the different flavors of streaming methods
- no extra runtime changes required
- allows the easy extension later to "translate" (/"fake"?) the different streaming flavors

Cons:
- still no guarantees that a model will implement all of the stream flavors
- which flavors of streaming are supported by a module is implicit, not explicit
- does not allow the easy extension later to multi-task models


### Noodle 3: Task loads?

```python
@caikit.task(required_params={"tokens": Iterable[str]}, output_type=Iterable[TokenClassification])
class StreamingTokenClassification(caikit.core.TaskBase):
  pass

@caikit.task(required_params={"text": str}, output_type=TokenClassifications)
class TokenClassification(caikit.core.TaskBase):
  pass


@caikit.module(id="foobar", task={StreamingTokenClassification: "run_bidi_stream", TokenClassification: "run"})
class MyTokenClassifier(caikit.core.ModuleBase):
  def run_bidi_stream(self, tokens: DataStream[str], threshold: float) -> DataStream[TokenClassification]:
    ...
  
  def run(self, text: str, threshold: float) -> TokenClassifications:
    ...


multi_task_model = caikit.load("/path/to/foobar")

dir(multi_task_model) # -> (run, run_bidi_stream, ...)

streaming_token_classifier = StreamingTokenClassification.load("/path/to/foobar")

dir(streaming_token_classifier) # -> (run, ...)



class TaskBase:

    @classmethod
    def load(cls, model_path):
        model = caikit.load(model_path)
        assert cls in model.TASKS
        run_fn_name = model.TASKS[cls]
        
        model.setattr("run", model.getattr(run_fn_name))
        model.delattrs("all" "other" "run" "functions")
        return  model
```

Wonky but works?

```python

@caikit.module(id="foobar", tasks=(StreamingTokenClassification, TokenClassification))
class MyTokenClassifier(caikit.core.ModuleBase):
  @taskmethod(StreamingTokenClassification)
  def run_bidi_stream(self, tokens: DataStream[str], threshold: float) -> DataStream[TokenClassification]:
    ...
  
  @taskmethod(TokenClassification)
  def run(self, text: str, threshold: float) -> TokenClassifications:
    ...

  @taskmethod(StreamingTokenClassification)
  @backendmethod(TGIS)
  def run_via_tgis(self, text: str, threshold: float):
    ...


  @classmethod
  def load(cls, model_path):
    if caikit.backend_enabled(TGIS):
       
```



### Stories?

If going with option 2:

- Add streaming on the input side of the tasks as well
(Assuming only a single input?)
- Decide on a multi-task API for modules
- Update _all_ the logic for api generation to support multiple tasks
-


Why multi-task models?
```python
import caikit


@caikit.module(id="foobar", tasks=(Sentiment, Entities))
class MyMultiTaskLLM:

    @taskmethod(Entities)
    def run_entities(self, text: str) -> Entities:
      generated_text = self.llm_module.run(text, prompt=self.entities_prompt)
      entities = self.entities_postprocess_module.run(generated_text)
      clean_entities = self.hap_module.run(entities)
      return clean_entities
      
    def run_sentiment(self, text: str) -> Sentiment:

```
The above uses a single model 