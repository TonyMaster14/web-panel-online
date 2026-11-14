"""Eight protocol/node combinations: every generated endpoint must be real."""
import unittest
import wpo_protocol_plan as plan


def node(*protocols):
    return {"online": True, "vpn_ready": True,
            "capabilities": ["federation", *protocols]}


class ProtocolPlanningTests(unittest.TestCase):
    def setUp(self):
        self.nl = node(*plan.CATALOG)
        self.se = node(*plan.CATALOG)
        self.registry = {"nl": self.nl, "se": self.se}

    def test_exactly_eight_protocol_backends(self):
        self.assertEqual([p.key for p in plan.PROTOCOLS],
            ["vless", "hysteria", "web", "mtproto",
             "awg20", "awg31", "naive", "mieru"])

    def test_two_nodes_two_happ_protocols_make_four_connections_one_feed(self):
        p = plan.plan_subscription(["nl", "se"], ["vless", "hysteria"], self.registry)
        self.assertEqual(p["connection_count"], 4)
        self.assertTrue(p["happ_subscription"]["one_url"])
        self.assertEqual([(r["node_id"], r["protocol"])
                          for r in p["happ_subscription"]["connections"]],
                         [("nl", "vless"), ("se", "vless"),
                          ("nl", "hysteria"), ("se", "hysteria")])
        self.assertEqual(p["telegram_links"], [])
        self.assertEqual(p["amnezia_profiles"], [])

    def test_amnezia_requires_one_real_node_and_native_config(self):
        with self.assertRaisesRegex(plan.PlanError, "одну конкретную ноду"):
            plan.plan_subscription(["nl", "se"], ["awg20"], self.registry)
        p = plan.plan_subscription(["nl", "se"], ["awg20", "awg31"],
                                   self.registry, amnezia_node="se")
        self.assertFalse(p["happ_subscription"]["one_url"])
        self.assertEqual([(x["node_id"], x["protocol"])
                          for x in p["amnezia_profiles"]],
                         [("se", "awg20"), ("se", "awg31")])
        self.assertEqual(p["connection_count"], 2)

    def test_all_eight_are_routed_to_matching_client_formats(self):
        p = plan.plan_subscription(["nl"], list(plan.CATALOG), self.registry)
        self.assertEqual(p["connection_count"], 8)
        self.assertEqual(len(p["happ_subscription"]["connections"]), 2)
        self.assertEqual([x["protocol"] for x in p["telegram_links"]],
                         ["web", "mtproto"])
        self.assertEqual([x["protocol"] for x in p["amnezia_profiles"]],
                         ["awg20", "awg31"])
        self.assertEqual([x["protocol"] for x in p["other_native_links"]],
                         ["naive", "mieru"])
        self.assertFalse(any(x["link_ready"] for groups in
            (p["happ_subscription"]["connections"],p["telegram_links"],
             p["amnezia_profiles"],p["other_native_links"]) for x in groups))

    def test_one_node_one_protocol(self):
        for proto in plan.CATALOG:
            with self.subTest(protocol=proto):
                p = plan.plan_subscription(["se"], [proto], self.registry)
                self.assertEqual(p["connection_count"], 1)

    def test_no_phantom_node_if_service_unavailable(self):
        self.registry["se"] = node("vless", "hysteria")
        for proto in ("web", "mtproto", "awg20", "awg31", "naive", "mieru"):
            with self.subTest(protocol=proto), self.assertRaisesRegex(plan.PlanError, "не готова"):
                plan.plan_subscription(["se"], [proto], self.registry)
        p = plan.plan_subscription(["nl", "se"], ["hysteria"], self.registry)
        self.assertEqual(p["connection_count"], 2)

    def test_no_offline_node_even_if_cached_capabilities_are_full(self):
        self.registry["se"]["vpn_ready"] = False
        with self.assertRaises(plan.PlanError):
            plan.plan_subscription(["nl", "se"], ["vless"], self.registry)

    def test_invalid_ambiguous_or_duplicate_choices_rejected(self):
        attempts = [
            (["nl", "nl"], ["vless"]),
            (["nl"], ["vless", "vless"]),
            (["nl"], ["reality"]),
            ([], ["vless"]),
            (["other"], ["vless"]),
            (["nl"], []),
        ]
        for nodes, protocols in attempts:
            with self.subTest(nodes=nodes, protocols=protocols), self.assertRaises(plan.PlanError):
                plan.plan_subscription(nodes, protocols, self.registry)


if __name__ == "__main__":
    unittest.main()
