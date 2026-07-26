Essentially:

We are building a AI-powered to-do list which has the ability to complete things locally for you.
For example: 
If I enter ‘AP world notes’ into the to-do list, then i can upload the document which i’m supposed to take notes on, it 

To-do list which can take in all inputs: emails, homework, calendar events, to-do list, and then execute things for you.
‘I have 5 unread emails’ -> it will go through them, draft them, and take earlier context. Then you can put in more context so it performs better and approve it’s draft for sending.
Then it can schedule time in your calendar (potentially)
It could have a similar intent as claude dispatch

For a hackathon, we are building an AI-powered automation that can control your computer and can do tasks for you. One big advantage to this is that it can run locally on the NVIDIA DGX Spark (as this is a key requirement for the hackathon). Here is a couple of examples of what it should be able to do:

I should be able to input some kind of prompt or objective of what I want it to complete for me, such as “Write an email to a certain person outline xyz.” or “Find the best hand soap on Amazon and order it for me.”
Including what I said above, it should be able to pull objectives from other sources (such as To-Do list apps, documents, etc.) and act on it as well.
It should have the following actions for every single task: It should take the objective as an input, think about an action plan, and execute on it. 
It should work in such a way that I will not need to assist it in any way possible. It should ideally do everything by itself (other than giving the primary objective).
It should act as a layer on top of OpenShell, OpenClaw or NemoClaw that runs as a GUI app specifically optimized for this use case. 

Here are key requirements you need to abide by:

It must use OpenShell, OpenClaw or NemoClaw in some way shape or form.
All computing must be done locally on an NVIDIA DGX Spark.

Here is what you need to do.

You need to build a full scale execution plan that can be built within 6 hours.
