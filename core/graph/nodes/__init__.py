"""
Реестр узлов по умолчанию. Все типы узлов Фазы 0 регистрируются здесь.

Добавить новый узел = создать класс Node и дописать его в _ALL_NODES.
Палитра редактора и исполнитель подхватят его автоматически.
"""

from __future__ import annotations

from ..registry import NodeRegistry
from .assembly import BlockListNode, StaticTaskNode, TaskNode
from .compute import ConstraintNode, FormulaNode, TemplateNode, VarDictNode
from .content import TextBlockNode, TextNode, ToBlockNode
from .control import (
    BoolNumberNode, CompareNode, GuardNode, NumberCheckNode, PickNode,
    SelectNode,
)
from .english import (
    SentencePickNode, SentencesFileNode,
    WordsFileNode, WordsPickNode,
    WordsTrainerNode,
)
from .image import ImageBlockNode, ImageFileNode, LogicCircuitNode
from .informatics import BaseNameNode, NumberBaseNode, PrefixCodeNode
from .pools import PoolNode, PoolPickNode
from .strings import LetterKeysNode, RandomWordNode, TextLengthNode
from .plot import (
    ComplexPointsPlotNode, ComplexRegionPlotNode, ConformalMapPlotNode,
)
from .lists import (
    ListAppendNode, ListConcatNode, ListGetNode, ListJoinNode, ListLengthNode,
    ListNewNode, RandomChoiceNode,
)
from .loop import (
    CaseNode, InputVarNode, LoopIndexNode, MapItemNode, MapNode, OutputVarNode,
    RepeatNode, ShiftGetNode, ShiftSetNode,
)
from .sources import (
    ConstantBoolNode, ConstantNumberNode, ConstantStringNode,
    NumberRangeNode, RandomNaturalNode, RandomRealNode, StringListNode,
)
from .task_macros import SimpleTaskNode
from .linalg import (
    ChangeBasisOperatorNode, CharPolyNode, CoordinatesInBasisNode,
    CrossProductNode, DeterminantNode, DotProductNode, EigenvaluesNode,
    EigenvectorsNode, GramSchmidtNode, IdentityNode, InverseNode,
    LineCanonicalNode, LinSolveNode, ListToMatrixNode, MatrixAddNode,
    MatrixBlockNode, MatrixConstNode, MatrixMultiplyNode, MatrixPowerNode,
    MatrixToQuadFormNode, NormNode, NullspaceNode, PlaneFromPointNormalNode,
    PointPlaneDistanceNode, QuadFormCanonicalNode, QuadFormSignatureNode,
    QuadFormToMatrixNode, RandomMatrixNode, RankNode, RrefNode,
    ScalarMultiplyNode, TraceNode, TransposeNode, TripleProductNode,
    VectorAngleNode,
)
from .ode import (
    OdeCheckNode, OdeClassifyNode, OdeConstNode, OdeSolveNode,
)
from .symbolic import (
    AbsNode, ApartNode, ArgNode, CancelNode, CollectNode, ConjugateNode,
    DiffNode, EvaluateNode, ExpandComplexNode, ExpandNode, ExprBinaryNode,
    ExprBlockNode, ExprCallNode, ExprConstNode, ExprLambdaNode, ExprLogNode, ExprReduceNode,
    FactorNode,
    FourierNode, ImNode,
    IntegrateNode, InverseFourierNode, InverseLaplaceNode, IsConvergentNode,
    LaplaceNode, LimitNode, LimitDisplayNode, ParseExprNode,
    RandomPolynomialNode, ReNode, ResidueNode,
    SeriesNode, SimplifyNode, SolveNode, SubsExprNode, SubstituteNode,
    SumDisplayNode, SummationNode, SymbolNode, TogetherNode, TrigsimpNode,
)

_ALL_NODES = [
    # task (макро-узлы — готовые задания)
    SimpleTaskNode,
    # source
    ConstantNumberNode, ConstantStringNode, ConstantBoolNode,
    RandomNaturalNode, RandomRealNode,
    StringListNode, NumberRangeNode, RandomChoiceNode,
    # compute
    VarDictNode, FormulaNode, ConstraintNode, TemplateNode,
    # control
    CompareNode, NumberCheckNode, SelectNode, PickNode, GuardNode,
    BoolNumberNode,
    LoopIndexNode, RepeatNode, MapItemNode, MapNode, InputVarNode,
    OutputVarNode, CaseNode,
    ShiftGetNode, ShiftSetNode,
    # symbolic (символьная арифметика)
    SymbolNode, ExprConstNode, ParseExprNode, RandomPolynomialNode,
    ExpandNode, FactorNode, SimplifyNode, TogetherNode, CancelNode, TrigsimpNode,
    CollectNode, ApartNode, ExprBinaryNode, ExprReduceNode, SubstituteNode,
    SubsExprNode,
    ExprLambdaNode, ExprCallNode, ExprLogNode,
    EvaluateNode,
    DiffNode, IntegrateNode, LimitNode, LimitDisplayNode, SeriesNode,
    SummationNode, SumDisplayNode, IsConvergentNode,
    ReNode, ImNode, ArgNode, AbsNode, ConjugateNode, ExpandComplexNode,
    ResidueNode, SolveNode,
    LaplaceNode, InverseLaplaceNode, FourierNode, InverseFourierNode,
    ExprBlockNode,
    # linalg (линейная алгебра)
    MatrixConstNode, RandomMatrixNode, IdentityNode, ListToMatrixNode,
    DeterminantNode, InverseNode, TransposeNode, RankNode, TraceNode,
    ScalarMultiplyNode, MatrixPowerNode, MatrixMultiplyNode, MatrixAddNode,
    RrefNode, CharPolyNode, EigenvaluesNode, EigenvectorsNode, NullspaceNode,
    LinSolveNode,
    DotProductNode, CrossProductNode, TripleProductNode, NormNode,
    VectorAngleNode, PlaneFromPointNormalNode, PointPlaneDistanceNode,
    LineCanonicalNode,
    QuadFormToMatrixNode, MatrixToQuadFormNode, QuadFormCanonicalNode,
    QuadFormSignatureNode, ChangeBasisOperatorNode, CoordinatesInBasisNode,
    GramSchmidtNode,
    MatrixBlockNode,
    # ode (дифференциальные уравнения)
    OdeConstNode, OdeSolveNode, OdeClassifyNode, OdeCheckNode,
    # english (английский язык)
    WordsFileNode, WordsPickNode, WordsTrainerNode, SentencesFileNode,
    SentencePickNode,
    # пулы значений и строки (общие: русский, английский, информатика)
    PoolNode, PoolPickNode, RandomWordNode, LetterKeysNode,
    TextLengthNode,
    # informatics (информатика)
    NumberBaseNode, BaseNameNode, PrefixCodeNode,
    # image (изображения / ОПВС)
    LogicCircuitNode, ImageFileNode, ImageBlockNode,
    # plot (графика на комплексной плоскости)
    ComplexPointsPlotNode, ComplexRegionPlotNode, ConformalMapPlotNode,
    # list (операции со списками)
    ListNewNode, ListAppendNode, ListConcatNode, ListLengthNode, ListGetNode,
    ListJoinNode,
    # content
    TextNode, TextBlockNode, ToBlockNode,
    # assembly
    TaskNode, BlockListNode, StaticTaskNode,
]


def build_default_registry() -> NodeRegistry:
    reg = NodeRegistry()
    for cls in _ALL_NODES:
        reg.register(cls)
    from .descriptions import apply_descriptions
    apply_descriptions(reg)
    return reg


# Готовый реестр для исполнителя и генератора.
DEFAULT_REGISTRY = build_default_registry()

__all__ = ["build_default_registry", "DEFAULT_REGISTRY"]
