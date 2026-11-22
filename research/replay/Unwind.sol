// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;
struct MP {address loanToken;address collateralToken;address oracle;address irm;uint256 lltv;}
interface IERC20 {function balanceOf(address) external view returns(uint256); function approve(address,uint256) external returns(bool);function transfer(address,uint256) external returns(bool);}
interface IMorpho {
 function idToMarketParams(bytes32) external view returns(MP memory);
 function position(bytes32,address) external view returns(uint256,uint128,uint128);
 function repay(MP memory,uint256,uint256,address,bytes memory) external returns(uint256,uint256);
 function withdrawCollateral(MP memory,uint256,address,address) external;
 function flashLoan(address,uint256,bytes memory) external;
}
interface IPendle {function swapExactPtForSy(address,uint256,bytes memory) external returns(uint256,uint256);}
interface ISY {function redeem(address,uint256,address,uint256,bool) external returns(uint256);}
interface ICurve {function exchange(int128,int128,uint256,uint256) external returns(uint256);}
interface IV3 {struct Input {address tokenIn;address tokenOut;uint24 fee;address recipient;uint256 amountIn;uint256 amountOutMinimum;uint160 sqrtPriceLimitX96;}function exactInputSingle(Input memory) external payable returns(uint256);}
contract Unwind {
 address constant MORPHO=address(bytes20(hex"bbbbbbbbbb9cc5e90e3b3af64bdaf62c37eeffcb"));
 address constant USDC=address(bytes20(hex"a0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"));
 address constant PT=address(bytes20(hex"b195b618ea52b77cb2a58846f452f59f8dfa9390"));
 address constant SY=address(bytes20(hex"bf98480425a29197e5d99d003017f63a1e595d02"));
 address constant SUSDE=address(bytes20(hex"9d39a5de30e57443bff2a8307a4256c8797a3497"));
 address constant MARKET=address(bytes20(hex"47ad2cd1dd15739a7a035b9d3b7828d916fef77e"));
 address constant CRVUSD=address(bytes20(hex"f939e0a03fb07f59a73314e73794be0e57ac1b4e"));
 address constant CURVE_A=address(bytes20(hex"57064f49ad7123c92560882a45518374ad982e85"));
 address constant CURVE_B=address(bytes20(hex"4dece678ceceb27446b35c672dc7d61f30bad69e"));
 address constant ROUTER=address(bytes20(hex"68b3465833fb72a70ecdf485e0e4c7bd8665fc45"));
 bytes32 constant ID=hex"5613b170ded221c588b6e9637b910f49e5508680ceede207f44aa72e5c46cb05";
 address owner;uint256 quantity;uint256 repayment;address middle;uint24 firstFee;uint24 secondFee;
 event Stage(uint256 indexed stage,uint256 amount);
 event Completed(uint256 collateralRemoved,uint256 usdcOutput,uint256 debtRepaid,uint256 residualShares,uint256 residualCollateral,uint256 ownerCash);
 error ShortOutput(uint256 received,uint256 required);
 constructor(){IERC20(USDC).approve(MORPHO,type(uint256).max);IERC20(SUSDE).approve(ROUTER,type(uint256).max);IERC20(SUSDE).approve(CURVE_A,type(uint256).max);IERC20(CRVUSD).approve(CURVE_B,type(uint256).max);}
 function run(address who,uint256 q,uint256 amount,address intermediate,uint24 f1,uint24 f2) external {
  require(block.chainid==31337,"local fork only");owner=who;quantity=q;repayment=amount;middle=intermediate;firstFee=f1;secondFee=f2;
  if(intermediate!=USDC){(bool ok,)=intermediate.call(abi.encodeWithSignature("approve(address,uint256)",ROUTER,type(uint256).max));require(ok,"approval failed");}
  IMorpho(MORPHO).flashLoan(USDC,amount,"");
 }
 function onMorphoFlashLoan(uint256 assets,bytes calldata) external {
  require(msg.sender==MORPHO);MP memory mp=IMorpho(MORPHO).idToMarketParams(ID);
  (,uint128 debtShares,uint128 originalCollateral)=IMorpho(MORPHO).position(ID,owner);
  uint256 paid;
  if(quantity==originalCollateral)(paid,)=IMorpho(MORPHO).repay(mp,0,debtShares,owner,"");
  else (paid,)=IMorpho(MORPHO).repay(mp,repayment,0,owner,"");
  emit Stage(1,paid);
  IMorpho(MORPHO).withdrawCollateral(mp,quantity,owner,address(this));emit Stage(2,quantity);
  IERC20(PT).transfer(MARKET,quantity);
  (uint256 syOut,)=IPendle(MARKET).swapExactPtForSy(address(this),quantity,"");emit Stage(3,syOut);
  uint256 susde=ISY(SY).redeem(address(this),syOut,SUSDE,0,false);emit Stage(4,susde);
  uint256 output;
  if(firstFee==0){uint256 crv=ICurve(CURVE_A).exchange(1,0,susde,0);output=ICurve(CURVE_B).exchange(1,0,crv,0);}
  else {output=IV3(ROUTER).exactInputSingle(IV3.Input(SUSDE,middle,firstFee,address(this),susde,0,0));
  if(middle!=USDC)output=IV3(ROUTER).exactInputSingle(IV3.Input(middle,USDC,secondFee,address(this),output,0,0));}
  emit Stage(5,output);
  uint256 cash=IERC20(USDC).balanceOf(address(this));
  if(cash<assets)revert ShortOutput(cash,assets);
  (,uint128 remainingShares,)=IMorpho(MORPHO).position(ID,owner);
  uint256 extra;
  if(remainingShares>0 && cash>assets)(extra,)=IMorpho(MORPHO).repay(mp,cash-assets,0,owner,"");
  uint256 excess=IERC20(USDC).balanceOf(address(this))-assets;
  if(excess>0)IERC20(USDC).transfer(owner,excess);
  (,uint128 finalShares,uint128 finalCollateral)=IMorpho(MORPHO).position(ID,owner);
  emit Completed(quantity,output,paid+extra,finalShares,finalCollateral,excess);
 }
}
