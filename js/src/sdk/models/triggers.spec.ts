import { beforeAll, describe, expect, it } from "@jest/globals";
import { getBackendClient } from "../testUtils/getBackendClient";

import { Entity } from "./Entity";
import { Actions } from "./actions";
import { ConnectedAccounts } from "./connectedAccounts";
import { Triggers } from "./triggers";

describe("Apps class tests", () => {
  let backendClient;
  let triggers: Triggers;
  let _connectedAccounts: ConnectedAccounts;
  let _entity: Entity;
  let _actions: Actions;

  beforeAll(() => {
    backendClient = getBackendClient();
    triggers = new Triggers(backendClient);
    _connectedAccounts = new ConnectedAccounts(backendClient);
    _entity = new Entity(backendClient, "default");
    _connectedAccounts = new ConnectedAccounts(backendClient);
    _actions = new Actions(backendClient);
  });

  it("should create an Apps instance and retrieve apps list", async () => {
    const triggerList = await triggers.list();
    expect(triggerList.length).toBeGreaterThan(0);
  });

  it("should retrieve a list of triggers for a specific app", async () => {
    const triggerList = await triggers.list({
      appNames: ["github"],
    });
    // this is breaking for now
    expect(triggerList.length).toBeGreaterThan(0);
    expect(triggerList[0].appName).toBe("github");
  });
});

describe("Apps class tests subscribe", () => {
  let backendClient;
  let triggers: Triggers;
  let connectedAccounts: ConnectedAccounts;
  let _actions: Actions;
  let _entity: Entity;

  let triggerId: string;

  beforeAll(() => {
    backendClient = getBackendClient();
    triggers = new Triggers(backendClient);
    connectedAccounts = new ConnectedAccounts(backendClient);
    _entity = new Entity(backendClient, "default");
    _actions = new Actions(backendClient);
  });

  it("should create a new trigger for gmail", async () => {
    const connectedAccount = await connectedAccounts.list({
      user_uuid: "default",
    });

    const connectedAccountId = connectedAccount.items.find(
      (item) => item.appName === "gmail"
    )?.id;
    if (!connectedAccountId) {
      throw new Error("No connected account found");
    }
    const trigger = await triggers.setup({
      connectedAccountId,
      triggerName: "gmail_new_gmail_message",
      config: {
        userId: connectedAccount.items[0].id,
        interval: 60,
        labelIds: "INBOX",
      },
    });

    expect(trigger.status).toBe("success");
    expect(trigger.triggerId).toBeTruthy();

    triggerId = trigger.triggerId;
  });

  it("should disable, enable, and then disable the created trigger", async () => {
    let trigger = await triggers.disable(triggerId);
    expect(trigger.status).toBe("success");

    trigger = await triggers.enable(triggerId);
    expect(trigger.status).toBe("success");

    trigger = await triggers.disable(triggerId);
    expect(trigger.status).toBe("success");
  });

  // it("should subscribe to a trigger and receive a trigger", async () => {
  //     function waitForTriggerReceived() {
  //         return new Promise((resolve) => {
  //             triggers.subscribe((data) => {
  //                 resolve(data);
  //             }, {
  //                 appName: "github",
  //                 triggerName: "GITHUB_ISSUE_ADDED_EVENT"
  //             });

  //             setTimeout(async () => {
  //                 const actionName = "github_create_an_issue";
  //                 // Not urgent
  //                 const connectedAccountsResult = await connectedAccounts.list({ integrationId: 'ca85b86b-1198-4e1a-8d84-b14640564c77' });
  //                 const connectionId = connectedAccountsResult.items[0].id;

  //                 await actions.execute({
  //                     actionName,
  //                     requestBody: {
  //                         connectedAccountId: connectionId,
  //                         input: {
  //                             title: "test",
  //                             owner: "ComposioHQ",
  //                             repo: "test_repo",
  //                         },
  //                         appName: 'github'
  //                     }
  //                 });
  //             }, 4000);
  //         });
  //     }

  //     const data = await waitForTriggerReceived();

  //     //@ts-ignore
  //     expect(data.payload.triggerName).toBe("GITHUB_ISSUE_ADDED_EVENT");

  //     triggers.unsubscribe();
  // });
});
