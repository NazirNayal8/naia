"""Verify dependency projections without inventing module execution edges."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

VIEWER = Path(__file__).resolve().parents[1] / "src/naia_arch/assets/viewer.js"


@unittest.skipUnless(shutil.which("node"), "Pure viewer tests require Node")
class ViewerFlowTest(unittest.TestCase):
    def evaluate(self, source):
        script = "const lens=require(" + json.dumps(str(VIEWER)) + ");\n" + source
        result = subprocess.run([shutil.which("node"), "-e", script], check=True,
                                capture_output=True, text=True)
        return json.loads(result.stdout)

    def test_type_dimensions_and_explicit_names(self):
        result = self.evaluate("""
          console.log(JSON.stringify({
            type:lens.nodeType({display_type:'Linear',config:{in_features:4,out_features:8}}),
            alias:lens.nodeTitle({label:'State projection',display_type:'Linear',kind:'operation',module_path:'projector'}),
            input:lens.nodeTitle({label:'Actions',kind:'input',type:'placeholder'}),
            shapes:lens.shapeSummary([{shape:[2,4,8]}, {shape:[2,2]}])
          }));
        """)
        self.assertEqual(result["type"], "Linear 4→8")
        self.assertEqual(result["alias"], "State projection")
        self.assertEqual(result["input"], "Actions")
        self.assertEqual(result["shapes"], "2 × 4 × 8 · 2 × 2")

    def test_collapsed_flow_preserves_input_to_output_and_skips_unused(self):
        result = self.evaluate("""
          const graph={schema_version:1,capture_mode:'runtime_observed',nodes:[
            {id:'root',parent:null}, {id:'input',parent:'root',kind:'input'},
            {id:'hidden',parent:'root',type:'Linear'}, {id:'unused',parent:'root',type:'Linear'},
            {id:'op',parent:'hidden',kind:'operation',type:'call_function'},
            {id:'output',parent:'root',kind:'output'}],edges:[
            {source:'input',target:'op',evidence:'observed'},
            {source:'op',target:'output',evidence:'observed'}],events:[],
            dataflow:{engine:'torch_dispatch',nodes:['input','op','output'],complete:true}};
          const saved=JSON.stringify(graph), model=lens.prepareGraph(graph);
          const state={projection:'flow',granularity:1,expand:new Map(),offsets:new Map()};
          const boxes=lens.layoutGraph(model,state), edges=lens.liftEdges(model,state);
          console.log(JSON.stringify({children:lens.activeChildren(model,'root',state),
            edges:edges.map(e=>[e.a,e.b]),positions:[boxes.get('input').x,boxes.get('hidden').x,boxes.get('output').x],
            hierarchy:lens.activeChildren(model,'root',{projection:'hierarchy'}),
            unchanged:saved===JSON.stringify(graph)}));
        """)
        self.assertNotIn("unused", result["children"])
        self.assertIn("unused", result["hierarchy"])
        self.assertEqual(result["edges"], [["input", "hidden"], ["hidden", "output"]])
        self.assertEqual(result["positions"], sorted(result["positions"]))
        self.assertEqual(len(set(result["positions"])), 3)
        self.assertTrue(result["unchanged"])

    def test_repeated_operations_not_merged_in_comparison(self):
        result = self.evaluate("""
          const graph={schema_version:1,capture_mode:'runtime_observed',nodes:[
            {id:'root',parent:null,module_path:''},
            {id:'op:1',parent:'root',kind:'operation',module_path:'shared',operation:'aten.addmm.default',call:1},
            {id:'op:2',parent:'root',kind:'operation',module_path:'shared',operation:'aten.addmm.default',call:2}],
            edges:[{source:'op:1',target:'op:2',evidence:'observed'}],events:[],
            dataflow:{engine:'torch_dispatch',nodes:['op:1','op:2'],complete:true}};
          const comparison=lens.comparisonGraph([{id:'A',title:'A',data:graph},{id:'B',title:'B',data:graph}],'B');
          const prepared=lens.prepareGraph(comparison.data);
          console.log(JSON.stringify({operations:comparison.data.nodes.filter(n=>n.kind==='operation').length,
            arrows:prepared.edges.length,self:prepared.edges.some(e=>e.source===e.target)}));
        """)
        self.assertEqual(result["operations"], 2)
        self.assertEqual(result["arrows"], 2)
        self.assertFalse(result["self"])

    def test_hierarchy_without_evidence_never_gets_inferred_arrows(self):
        result = self.evaluate("""
          const graph={schema_version:1,nodes:[{id:'root',parent:null},
            {id:'first',parent:'root'},{id:'second',parent:'root'}],edges:[],
            events:[{node:'first'},{node:'second'}]};
          const model=lens.prepareGraph(graph);
          console.log(JSON.stringify(lens.liftEdges(model,{projection:'flow',granularity:1,expand:new Map()})));
        """)
        self.assertEqual(result, [])

    def test_edge_shapes_include_scalar_and_legacy_metadata(self):
        result = self.evaluate("""
          console.log(JSON.stringify([
            lens.edgeShapeSummary({shape:[2,4]},null),
            lens.edgeShapeSummary({shape:[]},null),
            lens.edgeShapeSummary({shape:{shape:[2,8]}},null),
            lens.edgeShapeSummary({}, {shape:[3,8]})
          ]));
        """)
        self.assertEqual(result, ["2 × 4", "scalar", "2 × 8", "3 × 8"])

    def test_skip_edge_routing_preserves_clear_lanes_and_manual_bends(self):
        result = self.evaluate("""
          const a={x:0,y:100,w:174,h:112}, b={x:700,y:100,w:174,h:112};
          const middle={x:270,y:70,w:260,h:190};
          const route=lens.edgeRoute(a,b,{obstacles:[middle]});
          const next=lens.edgeRoute(a,b,{obstacles:[middle],lane:1});
          const manual=lens.edgeRoute(a,b,{obstacles:[middle],bend:[24,-180]});
          const direct=lens.edgeRoute(a,{x:270,y:100,w:174,h:112});
          function crosses(p,q) {
            return p[1]===q[1]
              ? p[1]>middle.y && p[1]<middle.y+middle.h &&
                Math.max(p[0],q[0])>middle.x && Math.min(p[0],q[0])<middle.x+middle.w
              : p[0]>middle.x && p[0]<middle.x+middle.w &&
                Math.max(p[1],q[1])>middle.y && Math.min(p[1],q[1])<middle.y+middle.h;
          }
          console.log(JSON.stringify({routed:route.routed,
            avoids:route.points.every((p,i)=>!i || !crosses(route.points[i-1],p)),
            distinct:route.label[1]!==next.label[1],
            bounded:route.points.every(([x,y])=>x>=route.bounds.x0 && x<=route.bounds.x1 &&
              y>=route.bounds.y0 && y<=route.bounds.y1),
            manual:manual.manual && !manual.routed, waypoint:manual.label,
            direct:!direct.routed && direct.d.includes(' C ')}));
        """)
        self.assertEqual(result["waypoint"], [459.5, -24])
        for key in ("routed", "avoids", "distinct", "bounded", "manual", "direct"):
            self.assertTrue(result[key], key)


if __name__ == "__main__":
    unittest.main()
