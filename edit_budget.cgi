#!/usr/bin/perl

use strict;
use warnings;

use DBI;
use Fcntl qw/:flock SEEK_END/;

require "./conf.pl";

our($db,$db_user,$db_pwd,$log_d,$doc_root,$upload_dir);

my %session;
my %auth_params;

my $id;
my $logd_in = 0;
my $authd = 0;
my $accountant = 0;

my $con;
my ($key,$iv,$cipher) = (undef, undef,undef);

if ( exists $ENV{"HTTP_SESSION"} ) {

	my @session_data = split/&/,$ENV{"HTTP_SESSION"};
	my @tuple;

	for my $unprocd_tuple (@session_data) {
		#came to learn (as often happens, purely by accident)
		#doing a split/=/,x= will give a list with a size of 1
		#desirable here (where it's OK to ignore unset vars)
		#would be awful where even a blank var means something (e.g
		#logging in with a blank password)
		@tuple = split/\=/,$unprocd_tuple;

		if (@tuple == 2) {
			$tuple[0] =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$tuple[1] =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$session{$tuple[0]} = $tuple[1];		
		}
	}

	#logged in 
	if (exists $session{"id"}) {
		$logd_in++;
		$id = $session{"id"};
		#only bursar(user 2) can edit budget
		if ( $id eq "2" ) {

			$accountant++;
			if (exists $session{"sess_key"} ) {
				$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});

				use MIME::Base64 qw /decode_base64/;
				use Crypt::Rijndael;

				my $decoded = decode_base64($session{"sess_key"});
				my @decoded_bytes = unpack("C*", $decoded);

				my @sess_init_vec_bytes = splice(@decoded_bytes, 32);
				my @sess_key_bytes = @decoded_bytes;

				#read enc_keys_mem
				my $prep_stmt3 = $con->prepare("SELECT init_vec,aes_key FROM enc_keys_mem WHERE u_id=? LIMIT 1");

				if ( $prep_stmt3 ) {

					my $rc = $prep_stmt3->execute($id);

					if ( $rc ) {

						my ($mem_init_vec, $mem_aes_key) = (undef,undef);

						while (my @rslts = $prep_stmt3->fetchrow_array()) {
							$mem_init_vec = $rslts[0];
							$mem_aes_key = $rslts[1];
						}

						if ( defined $mem_init_vec ) {

							my @mem_init_vec_bytes = unpack("C*", $mem_init_vec);
							my @mem_aes_key_bytes = unpack("C*", $mem_aes_key);

							my ( @decrypted_init_vec, @decrypted_aes_key );

							for (my $i = 0; $i < @mem_init_vec_bytes; $i++) {
								$decrypted_init_vec[$i] = $mem_init_vec_bytes[$i] ^ $sess_init_vec_bytes[$i];
							}

							for (my $j = 0; $j < @mem_aes_key_bytes; $j++) {
								$decrypted_aes_key[$j] = $mem_aes_key_bytes[$j] ^ $sess_key_bytes[$j];
							}

							$key = pack("C*", @decrypted_aes_key);
							$iv = pack("C*", @decrypted_init_vec);

							$cipher = Crypt::Rijndael->new($key, Crypt::Rijndael::MODE_CBC());
							$cipher->set_iv($iv);

							$authd++;

						}
					}
					else {
						print STDERR "Couldn't execute SELECT FROM enc_keys_mem: ", $prep_stmt3->errstr, $/;
					}

				}
				else {
					print STDERR "Couldn't prepare SELECT FROM enc_keys_mem: ", $prep_stmt3->errstr, $/;
				}
			}
		}
	}
}

my $content = '';
my $feedback = '';
my $js = '';

my $header =
qq{
<iframe width="30%" height=80 frameborder="1" src="/welcome2.html">
		<h5>Welcome to the </br>Spanj Accounts Management Information System</h5>
	</iframe>
	<iframe width="20%" height=80 frameborder="1" src="/cgi-bin/check_login.cgi?cont=/">
	</iframe>
	<p><a href="/">Home</a> --&gt; <a href="/accounts/">Accounts</a> --&gt; <a href="/cgi-bin/edit_budget.cgi">Edit Current Budget</a>
	<hr> 
};

unless ($authd) {
	if ($logd_in) {
		my $err = qq!<p><span style="color: red">Sorry, you do not have the appropriate privileges to edit the budget.</span> Only the bursar is authorized to take this action.!;

		#key issues?
		if ( $accountant ) {

			$err = qq!<p><span style="color: red">Sorry, could not obtain the encryption keys needed to manage accounts.</span> Try <a href="/cgi-bin/logout.cgi">logging out</a> and then log in again. If this problem persists, contact support.!;

		}

		$content .=
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj::Accounts Management Information System::Edit Budget</title>
</head>
<body>
$header

</body>
</html> 
*;
		print "Status: 200 OK\r\n";
		print "Content-Type: text/html; charset=UTF-8\r\n";

		my $len = length($content);
		print "Content-Length: $len\r\n";

		my @new_sess_array = ();

		for my $sess_key (keys %session) {
			push @new_sess_array, $sess_key."=".$session{$sess_key};        
		}
		my $new_sess = join ('&',@new_sess_array);

		print "X-Update-Session: $new_sess\r\n";

		print "\r\n";
		print $content;
		exit 0;
	}
	else {
		print "Status: 302 Moved Temporarily\r\n";
		print "Location: /login.html?cont=/cgi-bin/edit_budget.cgi\r\n";
		print "Content-Type: text/html; charset=UTF-8\r\n";
       		my $res = 
qq!
<html lang="en">
<head>
<title>Spanj::Accounts Management Information System</title>
</head>
<body>
$header
You should have been redirected to <a href="/login.html?cont=/cgi-bin/edit_budget.cgi">/login.html?cont=/cgi-bin/edit_budget.cgi</a>. If you were not, <a href="login.html?cont=/cgi-bin/edit_budget.cgi">Click Here</a> 
</body>
</html>!;

		my $content_len = length($res);	
		print "Content-Length: $content_len\r\n";
		print "\r\n";
		print $res;
		exit 0;
	}
}

my $post_mode = 0;
my $boundary = undef;
my $multi_part = 0;

if (exists $ENV{"REQUEST_METHOD"} and uc($ENV{"REQUEST_METHOD"}) eq "POST") {
	

	if (exists $ENV{"CONTENT_TYPE"}) {
		if ($ENV{"CONTENT_TYPE"} =~ m!multipart/form-data;\sboundary=(.+)!i) {
			$boundary = $1;
			$multi_part++;
		}
	}

	unless ($multi_part) {
		my $str = "";

		while (<STDIN>) {
        	       	$str .= $_;
	       	}

		my $space = " ";
		$str =~ s/\x2B/$space/ge;
		my @auth_req = split/&/,$str;

		for my $auth_req_line (@auth_req) {
			my $eqs = index($auth_req_line, "=");	
			if ($eqs > 0) {
				my ($k, $v) = (substr($auth_req_line, 0, $eqs), substr($auth_req_line, $eqs + 1)); 
				$k =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
				$v =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
				$auth_params{$k} = $v;
			}
		}
	}
	#processing data sent 
	$post_mode++;
}

use Digest::HMAC_SHA1 qw/hmac_sha1_hex/;

my $account_balances = qq!<em>You have not yet saved your bank accounts.</em> To do so, go to <a href="/cgi-bin/settings.cgi?act=chsysvars" target="_blank">Settings</a> and add a new variable named 'bank accounts'(without the quotes) containing a comma-separated list of all your bank accounts.!;

#read bank accounts
my %bank_accounts = ();

my $prep_stmt0 = $con->prepare("SELECT value FROM vars WHERE id='2-bank accounts' LIMIT 1");

if ($prep_stmt0) {

	my $rc = $prep_stmt0->execute();
	if ($rc) {
		while ( my @rslts = $prep_stmt0->fetchrow_array() ) {

			my @bank_accnts = split/,/,$rslts[0];

			foreach ( @bank_accnts ) {
				$bank_accounts{lc($_)} = {"name" => $_, "balance" => 0};
			}
		}
	}
	else {
		print STDERR "Couldn't execute SELECT FROM vars: ", $prep_stmt0->errstr, $/;
	}
}
else {
	print STDERR "Couldn't prepare SELECT FROM vars: ", $prep_stmt0->errstr, $/;
}

if ( scalar(keys %bank_accounts) > 0 ) {

	my $prep_stmt1 = $con->prepare("SELECT bank_account,amount,time,action_type,hmac FROM bank_actions WHERE bank_account=?");

	#my $prep_stmt1 = $con->prepare("INSERT INTO bank_actions VALUES(?,?,?,?,?)");

	if ($prep_stmt1) {

		for my $bank_account (keys %bank_accounts) {

			#this lc() is complicating a simple task
			my $accnt = ${$bank_accounts{$bank_account}}{"name"};
			#need to slurp to mem to sort by time 
			my %actions = ();
			my $enc_bank_account = $cipher->encrypt(add_padding($accnt));

			my $rc = $prep_stmt1->execute($enc_bank_account);
			if ($rc) {
				my $cntr = 0;

				while ( my @rslts = $prep_stmt1->fetchrow_array() ) {

					my $accnt = remove_padding($cipher->decrypt($rslts[0]));
					my $amount = remove_padding($cipher->decrypt($rslts[1]));
					my $time = remove_padding($cipher->decrypt($rslts[2]));
					my $action_type = remove_padding($cipher->decrypt($rslts[3]));
					
					#valid decryption
				if ( $amount =~ /^\d{1,10}(\.\d{1,2})?$/ ) {

						my $hmac = uc(hmac_sha1_hex($accnt . $amount . $time . $action_type, $key));

					#auth the data
						if ( $hmac eq $rslts[4] ) {
							$actions{$cntr++} = {"amount" => $amount, "time" => $time, "action_type" => $action_type};
						}
					}
				}

				foreach (sort { ${$actions{$a}}{"time"} <=> ${$actions{$b}}{"time"} } keys %actions ) {

				#init
					if ( ${$actions{$_}}{"action_type"} eq "3" ) {
						${$bank_accounts{$bank_account}}{"balance"} = ${$actions{$_}}{"amount"};
				}
				#withdrawal
				elsif ( ${$actions{$_}}{"action_type"} eq "2" ) {
					${$bank_accounts{$bank_account}}{"balance"} -= ${$actions{$_}}{"amount"};
				}
				#deposit
				elsif ( ${$actions{$_}}{"action_type"} eq "1" ) {
					${$bank_accounts{$bank_account}}{"balance"} += ${$actions{$_}}{"amount"};
				}
			}
		}

	else {
			print STDERR "Couldn't execute SELECT FROM bank_actions: ", $prep_stmt0->errstr, $/;
		}
	}
}
else {
	print STDERR "Couldn't prepare SELECT FROM bank_actions:", $prep_stmt0->errstr, $/;
}

$account_balances = "<TABLE>";

for my $bank_account ( sort { $a cmp $b } keys %bank_accounts ) {

	my $bank_account_name = htmlspecialchars(${$bank_accounts{$bank_account}}{"name"});

	$account_balances .= qq!<TR><TD><LABEL>$bank_account_name</LABEL><TD><span id="bank_account_${bank_account_name}_err" style="color: red"></span><INPUT type="text" name="bank_account_$bank_account_name" id="bank_account_$bank_account_name" value="${$bank_accounts{$bank_account}}{"balance"}" onkeyup="check_amount('bank_account_$bank_account_name')" onmousemove="check_amount('bank_account_$bank_account_name')">!;

	}
	$account_balances .= "</TABLE>";
}

#read current budget
my %votehead_hierarchy = ();
my $prep_stmt2 = $con->prepare("SELECT votehead,votehead_parent,amount,hmac FROM budget");
	
if ( $prep_stmt2 ) {

	my $rc = $prep_stmt2->execute();
	
	if ( $rc ) {

		while (my @rslts = $prep_stmt2->fetchrow_array()) {		

			my $decrypted_votehead = $cipher->decrypt( $rslts[0] );
			my $votehead = remove_padding($decrypted_votehead);

			my $decrypted_votehead_parent = $cipher->decrypt( $rslts[1] );
			my $votehead_parent = remove_padding($decrypted_votehead_parent);

			my $decrypted_amnt = $cipher->decrypt( $rslts[2] );	
			my $amnt = remove_padding($decrypted_amnt);

			#valid decryption
			if ( $amnt =~ /^\-?\d+(\.\d{1,2})?$/ ) {
				#check HMAC
				my $hmac = uc(hmac_sha1_hex($votehead . $votehead_parent . $amnt, $key));	
				if ( $hmac eq $rslts[3] ) {
					#did this to enable even parents
					#to record their budget amounts 
					if ( $votehead_parent eq "" ) {
						$votehead_parent = $votehead;
					}

					${$votehead_hierarchy{$votehead_parent}}{$votehead} = $amnt;	
				}
			}
		}
	}
	else {
		print STDERR "Couldn't prepare SELECT FROM budget:", $prep_stmt2->errstr, $/;
	}
}
else {
	print STDERR "Couldn't prepare SELECT FROM budget:", $prep_stmt2->errstr, $/;
}

PM: {
if ( $post_mode ) {

	#valid,non-automated request
	if ( not exists $auth_params{"confirm_code"} or not exists $session{"confirm_code"} or $auth_params{"confirm_code"} ne $session{"confirm_code"} ) {
		$feedback = qq!<span style="color: red">Invalid tokens sent.</span>!;
		$post_mode = 0;
		last PM;
	}

	my %errors = ();

	my %all_voteheads;
	my %new_account_balances;
	my %new_votehead_hierarchy = ();

	for my $auth_param (keys %auth_params) {

		if ($auth_param =~ /^bank_account_(.+)/) {

			my $bank_account = $1;
			my $balance = 0;

			if ( $auth_params{$auth_param} =~ /^\d+(\.\d{1,2})?$/ ) {
				$balance = $auth_params{$auth_param};
				#do not replace a good value with a bad one
				$new_account_balances{$bank_account} = $balance;
			}
			else {
				${$errors{qq!<span style="color: red">Invalid opening balance specified.</span> Defaulting to 0.!}}{$bank_account}++;
				$new_account_balances{$bank_account} = ${$bank_accounts{lc($bank_account)}}{"balance"};
			}
		}

		elsif ( $auth_param =~ /^votehead_(.+)/ and $auth_param !~ /votehead_amount/ ) {

			my $votehead_id = $1;
			my $votehead = $auth_params{$auth_param};

			unless (length($votehead) > 0) {
				next;
			}

			if ( length($votehead) > 31 ) {
				$votehead = substr($votehead, 0, 31);
				${$errors{qq!<span style="color: red">Specified votehead is longer than 31 characters.</span> Trimmed to 31 characters.!}}{$votehead}++;
			}

			my $votehead_parent = $votehead;

 
			if (exists $auth_params{"parent_votehead_$votehead_id"}) {
				$votehead_parent = $auth_params{"parent_votehead_$votehead_id"};
			}

			if ( length($votehead_parent) > 31 ) {
				$votehead_parent = substr($votehead_parent, 0, 31);

				#children of different parents with the same name
				if (exists $all_voteheads{$votehead}) {

					$votehead = "$votehead_parent($votehead)";

		 			if ( length($votehead) > 31 ) {
						$votehead = substr($votehead, 0, 31);	
					}	
				}
			}

			my $amount = 0;

			if ( exists $auth_params{"votehead_amount_$votehead_id"} and $auth_params{"votehead_amount_$votehead_id"} =~ /^\d+(?:\.\d{1,2})?$/) {
				$amount = $auth_params{"votehead_amount_$votehead_id"};
			}
			else {
				${$errors{qq!<span style="color: red">Invalid amount specified.</span> Defaulted to 0.!}}{$votehead}++;
			}

			${$new_votehead_hierarchy{$votehead_parent}}{$votehead} = $amount;
			$all_voteheads{$votehead}++;
		}
	}

	for my $votehead (keys %new_votehead_hierarchy) {

		my $votehead_amnt = ${$new_votehead_hierarchy{$votehead}}{$votehead};
		my $sub_category_total = 0;

		foreach ( keys %{$new_votehead_hierarchy{$votehead}} ) {

			next if ($_ eq $votehead);
			$sub_category_total += ${$new_votehead_hierarchy{$votehead}}{$_};

		}

		if ($sub_category_total > $votehead_amnt) {
			${$errors{qq!<span style="color: red">Total amount budgeted for sub-categories exceeds amount budgeted for entire votehead.</span> Saved votehead nonetheless.!}}{$votehead}++;
		}
	}

	#check for bank account difs
	my %account_updates;	

	for my $accnt (keys %new_account_balances) {

		my $lc_accnt = lc($accnt);

		if (not exists $bank_accounts{$lc_accnt} ) {
			$account_updates{$accnt} = $new_account_balances{$accnt};
		}

		elsif ( not ${$bank_accounts{$lc_accnt}}{"balance"} == $new_account_balances{$accnt} ) {
			$account_updates{$accnt} = $new_account_balances{$accnt};
		}
		
	}

	my %new_voteheads = ();
	my %updated_voteheads = ();

	my $cntr = 0;

	for my $votehead (keys %new_votehead_hierarchy) {
		#new top-level votehead 
		if ( not exists $votehead_hierarchy{$votehead} ) {

			my $amnt = ${$new_votehead_hierarchy{$votehead}}{$votehead};
			my $hmac = uc(hmac_sha1_hex($votehead . "" . $amnt, $key));

			$new_voteheads{$votehead} = {"votehead" => $cipher->encrypt(add_padding($votehead)), "parent" => $cipher->encrypt(add_padding("")), "amount" => $cipher->encrypt(add_padding($amnt)), "hmac" => $hmac};
			
			for my $child_votehead ( keys %{$new_votehead_hierarchy{$votehead}} ) {

				next if ($child_votehead eq $votehead);
				
				my $amnt = ${$votehead_hierarchy{$votehead}}{$child_votehead};
				my $hmac = uc(hmac_sha1_hex($child_votehead . $votehead . $amnt, $key));

				$new_voteheads{$child_votehead} = {"votehead" => $cipher->encrypt(add_padding($child_votehead)), "parent" => $cipher->encrypt(add_padding($votehead)), "amount" => $cipher->encrypt(add_padding($amnt)), "hmac" => $hmac};
	
			}

		}

		else {
			for my $child_votehead (keys %{$new_votehead_hierarchy{$votehead}}) {

				my $amnt = ${$new_votehead_hierarchy{$votehead}}{$child_votehead};

				my $parent = $votehead;
				if ($child_votehead eq $votehead) {
					$parent = "";
				}

				my $hmac = uc(hmac_sha1_hex($child_votehead . $parent . $amnt, $key));

				if ( not exists ${$votehead_hierarchy{$votehead}}{$child_votehead} ) {

					$new_voteheads{$child_votehead} = {"votehead" => $cipher->encrypt(add_padding($child_votehead)), "parent" => $cipher->encrypt(add_padding($votehead)), "amount" => $cipher->encrypt(add_padding($amnt)), "hmac" => $hmac};
	
				}
				elsif ( not $amnt == ${$votehead_hierarchy{$votehead}}{$child_votehead} ) {

					$updated_voteheads{$child_votehead} = {"votehead" => $cipher->encrypt(add_padding($child_votehead)), "amount" => $cipher->encrypt(add_padding($amnt)), "hmac" => $hmac};

				}
			}
		}
	}

	if (scalar(keys %account_updates) > 0) {

		my $prep_stmt3 = $con->prepare("INSERT INTO bank_actions VALUES(?,?,?,?,?)");

		if ($prep_stmt3) {

			my $time = time;

			my $encd_time = $cipher->encrypt(add_padding($time));
			my $encd_act_type = $cipher->encrypt(add_padding("3"));

			for my $accnt (keys %account_updates) {

				my $hmac = uc(hmac_sha1_hex($accnt . $account_updates{$accnt} . $time . "3", $key));
				my $encd_accnt = $cipher->encrypt(add_padding($accnt));
				my $encd_balance = $cipher->encrypt(add_padding($account_updates{$accnt}));
			
				$prep_stmt3->execute($encd_accnt, $encd_balance, $encd_time, $encd_act_type, $hmac);
			}
		}
		else {
			print STDERR "Couldn't prepare INSERT INTO bank_actions: ", $prep_stmt3->errstr, $/;
		}
	}


	#new voteheads
	if ( scalar (keys %new_voteheads) > 0 ) {

		my $prep_stmt4 = $con->prepare("INSERT INTO budget VALUES(?,?,?,?)");

		if ($prep_stmt4) {
			for my $votehead (keys %new_voteheads) {
				my $rc = $prep_stmt4->execute(${$new_voteheads{$votehead}}{"votehead"}, ${$new_voteheads{$votehead}}{"parent"},${$new_voteheads{$votehead}}{"amount"}, ${$new_voteheads{$votehead}}{"hmac"});
				unless ($rc) {
					print STDERR "Couldn't execute INSERT INTO budget: ", $prep_stmt4->errstr, $/;
				}
			}
		}
		else {
			print STDERR "Couldn't prepare INSERT INTO budget: ", $prep_stmt4->errstr, $/;
		}
	}

	#updated voteheads
	if ( scalar (keys %updated_voteheads) > 0 ) {

		my $prep_stmt5 = $con->prepare("UPDATE budget SET amount=?,hmac=? WHERE BINARY votehead=? LIMIT 1");

		if ($prep_stmt5) {

			for my $votehead ( keys %updated_voteheads ) {

				my $rc = $prep_stmt5->execute(${$updated_voteheads{$votehead}}{"amount"}, ${$updated_voteheads{$votehead}}{"hmac"}, ${$updated_voteheads{$votehead}}{"votehead"});
				unless ($rc) {
					print STDERR "Couldn't execute UPDATE budget: ", $prep_stmt5->errstr, $/;
				}

			}

		}
		else {
			print STDERR "Couldn't prepare UPDATE budget: ", $prep_stmt5->errstr, $/;
		}
	}

	#log action
	my @today = localtime;	
	my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];

	open (my $log_f, ">>$log_d/user_actions-$day_month_yr.log");
       	if ($log_f) {
       		@today = localtime;	
		my $time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];	
		flock ($log_f, LOCK_EX) or print STDERR "Could not log update budget for $id due to flock error: $!$/"; 
		seek ($log_f, 0, SEEK_END);
		print $log_f "$id UPDATE BUDGET $time\n";
		flock ($log_f, LOCK_UN);
               	close $log_f;
       	}
	else {
		print STDERR "Could not log update budget for $id: $!\n";
	}

	$con->commit();
	#add data to 
	my $errors_str = "";
	
	if (scalar(keys %errors) > 0) {
		$errors_str .= "However, there were the following issues:<ol>";
		foreach (keys %errors) {
			$errors_str .= "<li>" . $_ . ": " . join(", ", keys %{$errors{$_}}) . "<br>";
		}
		$errors_str .= "</ol>";
	}

	my $opening_balances_str = 
qq!

<TABLE>

<THEAD>
<TH>Bank Account
<TH>Amount
</THEAD>

<TBODY>

!;
	for my $accnt (keys %new_account_balances) {
		my $balance = format_currency($new_account_balances{$accnt});
		$opening_balances_str .= "<TR><TD>$accnt<TD>$balance";
	}

	$opening_balances_str .= "</TBODY></TABLE>";

	my $new_budget_str = 
qq!
<TABLE cellspacing="5%" cellpadding="5%" border="1" style="vertical-align: middle">
<THEAD>
<TH>Votehead
<TH>Sub-category
<TH>Budget Amount
</THEAD>
<TBODY>
!;

	for my $votehead (keys %new_votehead_hierarchy) {

		my ($colspan, $rowspan) = ("2", "1");

		my $sub_cat_val = "";	
		
		my $num_sub_categories = scalar(keys %{$new_votehead_hierarchy{$votehead}});

		if ($num_sub_categories  > 1 ) {
			$colspan = "1";
			$rowspan = $num_sub_categories;	
			$sub_cat_val = qq!<TD style="font-weight: bold">Total!;
		}
		
		my $amount = format_currency(${$new_votehead_hierarchy{$votehead}}{$votehead});

		$new_budget_str .= qq!<TR><TD rowspan="$rowspan" colspan="$colspan">$votehead$sub_cat_val<TD>$amount!;

		foreach ( keys %{$new_votehead_hierarchy{$votehead}} ) {

			next if ($_ eq $votehead);

			my $amount = format_currency(${$new_votehead_hierarchy{$votehead}}{$_});
			$new_budget_str .= qq!<TR><TD>$_<TD>$amount!;
		}

	}

	$new_budget_str .= "</TBODY></TABLE>";
	$content = 
qq*
<!DOCTYPE html>
<html lang="en">

<head>
<title>Spanj::Accounts Management Information System::Update Fee Balances</title>
</head>

<body>
$header
<p>The budget has been updated! You can <a href="/cgi-bin/edit_budget.cgi">edit it</a> at any time or <a href="/cgi-bin/create_fee_structure.cgi">publish a new fee structure</a> to go with it.
<p>$errors_str
<p>$opening_balances_str
<p>$new_budget_str
</body>
</html>
*;
}
}

if (not $post_mode) {

	my $voteheads = qq!<div id="voteheads">!;

	#allow base of 10 voteheads
	my $cntr = 0;
	for my $votehead (keys %votehead_hierarchy) {

		my $escaped_votehead = htmlspecialchars($votehead);
		my $amnt = ${$votehead_hierarchy{$votehead}}{$votehead};

		$voteheads .= qq!<div id="container_$escaped_votehead">!;

		$voteheads .= qq!<p><LABEL style="font-weight: bold" for="votehead_$escaped_votehead">Votehead</LABEL>&nbsp;<INPUT readonly type="text" value="$escaped_votehead" name="votehead_$escaped_votehead">&nbsp;&nbsp;&nbsp;<span style="color: red" id="votehead_amount_${escaped_votehead}_err"></span><LABEL style="font-weight: bold" for="votehead_amount_$escaped_votehead">Amount</LABEL>&nbsp;<INPUT type="text" name="votehead_amount_$escaped_votehead" id="votehead_amount_$escaped_votehead" value="$amnt" onkeyup="check_amount('votehead_amount_$escaped_votehead')" onmouseover="check_amount('votehead_amount_$escaped_votehead')">!;
		
		$voteheads .= qq!&nbsp;<INPUT type="button" value="Add sub-category" onclick="add_sub_category('$escaped_votehead')">!;

		for my $child_votehead ( keys %{$votehead_hierarchy{$votehead}} ) {

			$amnt = ${$votehead_hierarchy{$votehead}}{$child_votehead};
			next if ($child_votehead eq $votehead);

			my $spacer = "&nbsp;" x 5;

			my $escaped_child = htmlspecialchars($child_votehead);

			$voteheads .= qq!<p>$spacer<LABEL style="font-weight: bold" for="votehead_$escaped_child">Sub-category</LABEL>&nbsp;<INPUT type="hidden" name="parent_votehead_$escaped_child" value="$escaped_votehead"><INPUT readonly type="text" value="$escaped_child" name="votehead_$escaped_child">&nbsp;&nbsp;&nbsp;<span style="color: red" id="votehead_amount_${escaped_child}_err"></span><LABEL style="font-weight: bold" for="votehead_amount_$escaped_child">Amount</LABEL>&nbsp;<INPUT type="text" name="votehead_amount_$escaped_child" id="votehead_amount_$escaped_child" value="$amnt" onkeyup="check_amount('votehead_amount_$escaped_child')" onmouseover="check_amount('votehead_amount_$escaped_child')">!;
		}

		$voteheads .= "</div>";

		$cntr++;
	} 

	#allow 5 more voteheads
	my $extra = $cntr + 10;
	for (; $cntr < $extra; $cntr++) {

		$voteheads .= qq!<div id="container_$cntr">!;

		$voteheads .= qq!<p><LABEL style="font-weight: bold" for="votehead_$cntr">Votehead</LABEL>&nbsp;<INPUT type="text" value="" name="votehead_$cntr">&nbsp;&nbsp;&nbsp;<span style="color: red" id="votehead_amount_${cntr}_err"></span><LABEL style="font-weight: bold" for="votehead_amount_$cntr">Amount</LABEL>&nbsp;<INPUT type="text" name="votehead_amount_$cntr" id="votehead_amount_$cntr" value="" onkeyup="check_amount('votehead_amount_$cntr')" onmouseover="check_amount('votehead_amount_$cntr')">!;

		$voteheads .= qq!&nbsp;&nbsp;<INPUT type="button" value="Add sub-category" onclick="add_sub_category('$cntr')">!;
		$voteheads .= "</div>";
	}

	$voteheads .= "</div>";

	my $conf_code = gen_token();
	$session{"confirm_code"} = $conf_code;

	$content = 
qq*
<!DOCTYPE html>
<html lang="en">

<head>
<title>Spanj::Accounts Management Information System::Update Budget</title>

<script type="text/javascript">

var sub_cat_id = 11;
var num_re = /^([0-9]{0,10})(\\.([0-9]{0,2}))?\$/;

function check_amount(elem) {

	var amnt = document.getElementById(elem).value;
	var match_groups = amnt.match(num_re);

	if ( match_groups ) {
		document.getElementById(elem + "_err").innerHTML = "";
	}
	else {
		document.getElementById(elem + "_err").innerHTML = "\*";
	}
}

function add_sub_category(parent) {

	var new_sub = document.createElement("span");	

	new_sub.innerHTML = '<p>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;<LABEL style="font-weight: bold" for="votehead_' + sub_cat_id + '">Sub-category</LABEL>&nbsp;<INPUT type="hidden" name="parent_votehead_' + sub_cat_id + '" value="' + parent + '"><INPUT type="text" value="" name="votehead_' + sub_cat_id + '">&nbsp;&nbsp;&nbsp;<span style="color: red" id="votehead_amount_' + sub_cat_id + '_err"></span><LABEL style="font-weight: bold" for="votehead_amount_' + sub_cat_id + '">Amount</LABEL>&nbsp;<INPUT type="text" name="votehead_amount_' + sub_cat_id + '" id="votehead_amount_' + sub_cat_id + '" value="0" onkeyup="check_amount(\\'votehead_amount_' + sub_cat_id + '\\')" onmouseover="check_amount(\\'votehead_amount_' + sub_cat_id + '\\')">';

	document.getElementById("container_" + parent).appendChild(new_sub);
	sub_cat_id++;
}

</script>

</head>

<body>
$header
$feedback
<FORM method="POST" action="/cgi-bin/edit_budget.cgi">
<input type="hidden" name="confirm_code" value="$conf_code">
<h4>Bank Account Balances</h4>
$account_balances

<h4>Voteheads</h4>
<p>A <em>sub-category</em> is merely a way of organizing the budget. For instance, under tuition, you might create sub-categories such as: text books, stationery, lab equipment, and teaching aids. These sub-categories may be hidden during the preparation of balance sheets.
$voteheads
<p><INPUT type="submit" value="Save Changes" name="save">
</FORM>

</body>

</html>
*;

}

print "Status: 200 OK\r\n";
print "Content-Type: text/html; charset=UTF-8\r\n";

my $len = length($content);
print "Content-Length: $len\r\n";

my @new_sess_array = ();

for my $sess_key (keys %session) {
	push @new_sess_array, $sess_key."=".$session{$sess_key};        
}
my $new_sess = join ('&',@new_sess_array);

print "X-Update-Session: $new_sess\r\n";

print "\r\n";
print $content;
$con->disconnect() if (defined $con and $con);

sub gen_token {
	my @key_space = ("A","B","C","D","E","F","0","1","2","3","4","5","6","7","8","9");
	my $len = 5 + int(rand 15);
	if (@_ and ($_[0] eq "1")) {
		@key_space = ("A","B","C","D","E","F","G","H","J","K","L","M","N","P","T","W","X","Z","7","0","1","2","3","4","5","6","7","8","9");
		$len = 10 + int (rand 5);
	}
	my $token = "";
	for (my $i = 0; $i < $len; $i++) {
		$token .= $key_space[int(rand @key_space)];
	}
	return $token;
}

sub htmlspecialchars {
	my $cp = $_[0];
	$cp =~ s/&/&#38;/g;
        $cp =~ s/</&#60;/g;
        $cp =~ s/>/&#62;/g;
        $cp =~ s/'/&#39;/g;
        $cp =~ s/"/&#34;/g;
        return $cp;
}

sub remove_padding {

	return undef unless (@_);

	my $packed = $_[0];
	my @bytes = unpack("C*", $packed);
	
	my $final_index = $#bytes;
	my $pad_size = $bytes[$final_index];

	my $msg_valid = 1;
	#verify msg
	
	for ( my $i = 1; $i < $pad_size; $i++ ) {
		unless ( $bytes[$final_index - $i] == $pad_size ) {
			$msg_valid = 0;
			last;
		}
	}

	if ($msg_valid) {
		my $msg_size = ($final_index + 1) - $pad_size;
		my $msg = unpack("A${msg_size}", $packed);

		return $msg;
	}
	return undef;
}

sub add_padding {

	return undef unless (@_);

	my $tst_str = $_[0];
	my $tst_str_len = length($tst_str);

	my $rem = 16 - ($tst_str_len % 16);
	if ($rem == 0 ) {
		$rem = 16;
	}

	my @extras = ();
	for (my $i = 0; $i < $rem; $i++) {
		push @extras, $rem;
	}

	my $padded = pack("A${tst_str_len}C${rem}", $tst_str, @extras);
	return $padded;
}

sub format_currency {

	return "" unless (@_);

	my $formatted_num = $_[0];

	if ( $_[0] =~ /^(\-?)(\d+)(\.(?:\d))?$/ ) {

		my $sign = $1;
		my $shs = $2;
		my $cents = $3;

		$sign = "" if (not defined $sign);
		$cents = "" if (not defined $cents);

		my $num_blocks = int(length($shs) / 3);

		if ($num_blocks > 0) {

			my @nums = ();

			my $surplus = length($shs) % 3;
			if ($surplus > 0) {
				push @nums, substr($shs, 0, $surplus);
			}

			for (my $i = 0; $i < $num_blocks; $i++) {
				push @nums, substr($shs, $surplus + ($i * 3),3);
			}

			$formatted_num = join(",", @nums); 
		}

		$formatted_num = $sign . $formatted_num;
		$formatted_num .= $cents;
	}
	return $formatted_num;
}
