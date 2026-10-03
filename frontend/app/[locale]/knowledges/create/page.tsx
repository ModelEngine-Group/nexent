import AidpCreateKbPage from "@/ext_components/aidp/components/AidpCreateKbPage";

/**
 * Dedicated AIDP knowledge base creation entry.
 *
 * The page renders the AIDP creation flow only; the component sends a visitor
 * back to the knowledge base overview when the deployment does not have the
 * AIDP backend enabled. ES deployments keep their own creation flow and the
 * existing `knowledges` entry behavior is untouched.
 */
export default function AidpCreateKnowledgeBasePage() {
  return <AidpCreateKbPage />;
}
