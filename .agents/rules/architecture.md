---
trigger: always_on
---

Instructions for the implementation:

- The backend must be implemented using Python
- The game rules implementation should be extensible, meaning new games can be added in the future without modifying the backend code.
- The server code should be modular and well-organized.
- There must be a check for security issues before accepting any action.
- The action validation must be part of the specific game rules implementation, as well as the preparation of a new game state.
- To save the game state, use the database, but the create, read, update, delete, and query operations must use an interface, so I can change the database implementation in the future without modifying the backend code.
- To schedule the update check, use an interface, so I can change the scheduling implementation in the future without modifying the backend code.
- The code must be aware of the serverless architecture, so it can be deployed on any serverless platform provider.
- The code must be aware of the polling mechanism, so it can be used with any game engine.
- It must be aware that each update loop will run on intervals of at least 500ms.
- It supports multiple games, each with its own rules, running on the same backend, so when a session is created or an action is registered, the game rules implementation must be specified.
- Each run of the update loop must be independent of the others, meaning that the update loop should not rely on any state that is not passed to it.
- The game rules implementation must be able to save the game state to the database and retrieve it from the database.
- The game state must include a variable to check if the game is over, and if so, the session must be terminated.
- There may be multiple sessions running at the same time, so the code must be thread-safe.
- There must be a way to block players from spamming actions, so the code must check the time between actions and block the player if the time is too short.
- If there is no actions or no updates for a long time (e.g. 5 minutes), the session should be terminated.
- The session should have a maximum lifetime (e.g. 1 hour), after which it should be terminated.
- There may be specific configurations for each game, such as the update interval, the maximum number of players, etc. These configurations will be saved on the database and retrieved when the session is created.
- The session should have a unique identifier, which will be used to identify the session.
- The session should have a status, which will be used to identify the status of the session. The status can be 'active', 'inactive', 'terminated', etc.
- When the session is created, player information will be passed with additional data, such as player id and name. This information will be used to identify the player.
- The game state may be different for each requester, so the game rules implementation must be able to prepare a different game state for each requester. There will be public state variables and private state variables. The public state variables will be sent to all requesters, while the private state variables will be sent only to the requester who owns them.
- There should be a way to verify if the requester is who they claim to be, so the code must check the requester's id and name against the database. And a security token should be generated to verify the requester's identity. This token will be sent with each request and checked against the database.
- There is logic for the client and logic for the server, so the code must be aware of the difference between them. The client must not have access to any of the core logic, they only have access to the local implementation of the interfaces.
- 