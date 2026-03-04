PYSLAP is a python multiplayer game backend framework. It works on the cloud with a serverless architecture and has the following features:

- It does not rely on websockets for real-time communication. Instead, it uses a polling mechanism to send updates to the clients.
- It is implementation agnostic, meaning it can be used with any game engine and any serverless platform provider.
- It supports multiple games, each with its own rules, running on the same backend.

How it works:

A - For the client:

- A new session is requested.
- A polling loop is started.
- When a new game state is received, the client updates the game.
- At any time, the client may send an action to be registered.

B - For the server:

- A new session is created and an update check is scheduled.
- When the update check is triggered, the server checks registered player actions and updates the game state.
