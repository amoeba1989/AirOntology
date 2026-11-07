from app.main import app, AgentQuestion, QueryInput


def test_api_documentation_covers_routes_and_request_examples_are_valid():
    schema = app.openapi()
    for operations in schema['paths'].values():
        for operation in operations.values():
            assert operation.get('summary') and operation.get('description')
    models = schema['components']['schemas']
    for model in (QueryInput, AgentQuestion):
        for example in models[model.__name__]['examples']:
            model.model_validate(example)
