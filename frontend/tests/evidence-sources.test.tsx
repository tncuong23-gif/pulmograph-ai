import { expect,it } from "vitest";
import { render,screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ReactMarkdown from "react-markdown";
import { SourcesProvider,SourceCitation,SourcesList,numberedCitations } from "../src/components/chat/EvidenceSources";
const sources=[{number:1,title:"Tài liệu bệnh phổi",section:"Triệu chứng",text:"Đoạn nguồn nguyên văn, có điều kiện và phủ định.",origins:[{document_id:"DOC_HIDDEN",evidence_id:"SENT_HIDDEN"}]}];

it("shows hover/focus evidence and opens a keyboard-accessible source drawer without technical IDs",async()=>{
 const user=userEvent.setup();const view=render(<SourcesProvider sources={sources}><p>Trả lời <SourceCitation number={1}/></p><SourcesList/></SourcesProvider>);
 const button=screen.getAllByRole("button",{name:"Nguồn 1"})[0];
 await user.hover(button);
 expect(screen.getByRole("tooltip")).toHaveTextContent(sources[0].text);
 expect(screen.getByRole("tooltip").style.bottom).toBe("auto");
 expect(screen.queryByText("DOC_HIDDEN")).not.toBeInTheDocument();
 await user.unhover(button);expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
 await user.tab();expect(screen.getByRole("tooltip")).toBeInTheDocument();
 await user.keyboard("{Enter}");
 expect(screen.getByRole("dialog")).toHaveTextContent(sources[0].text);
 expect(screen.getByRole("dialog")).toHaveTextContent("Triệu chứng");
 await user.keyboard("{Escape}");expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
 expect(view.container.textContent).not.toContain("SENT_HIDDEN");
});

it("links plain numbered references while preserving code and existing web links",()=>{
 render(<ReactMarkdown remarkPlugins={[numberedCitations(sources)]}>{"Thông tin [1]. `code [1]` [website](https://example.com) [9]."}</ReactMarkdown>);
 expect(screen.getByRole("link",{name:"[1]"})).toHaveAttribute("href","#source-1");
 expect(screen.getByText("code [1]").tagName).toBe("CODE");
 expect(screen.getByRole("link",{name:"website"})).toHaveAttribute("href","https://example.com");
 expect(screen.queryByRole("link",{name:"[9]"})).not.toBeInTheDocument();
});

it("marks model output separately and renders untrusted source text as text",async()=>{
 const user=userEvent.setup();const {container}=render(<SourcesProvider sources={[{number:1,title:"Clinical IE",kind:"model",text:"<img src=x onerror=alert(1)>"}]}><SourceCitation number={1}/></SourcesProvider>);
 await user.click(screen.getByRole("button",{name:"Nguồn 1"}));
 expect(screen.getByRole("dialog")).toHaveTextContent("không phải bằng chứng tài liệu y khoa");
 expect(screen.getByText("<img src=x onerror=alert(1)>")).toBeVisible();
 expect(container.querySelector("img")).toBeNull();
});
